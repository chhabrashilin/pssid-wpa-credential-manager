#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# pssid-credmgr-pull - non-Ansible probe helper (PRD 9.5).
# Pulls a bundle render and installs it root:root 0600, honoring the ETag/304
# flow so an unchanged render is a no-op.
#
# pSSID daemon contract: the daemon opens one file per SSID profile, named
# /etc/wpa_supplicant/wpa_supplicant_{ssid_profile}.conf (pssid-daemon.py), so
# the bundle name doubles as the profile name and decides the file name. The
# wpa_supplicant service stays disabled on probes -- the daemon runs
# pssid-80211 against the file at batch time, so no restart is needed here.
#
# The render's ETag is the first 8 hex chars of the SHA-256 of its body, so
# If-None-Match is computed from the installed file itself. No state file is
# kept: a deleted or hand-edited file simply gets pulled again.
#
#   CREDMGR_TOKEN=xxx ./pssid-credmgr-pull.sh \
#     https://credmgr.example.edu eduroam
# ---------------------------------------------------------------------------
set -euo pipefail

BASE="${1:?usage: pssid-credmgr-pull.sh <base-url> <bundle>}"
BUNDLE="${2:?usage: pssid-credmgr-pull.sh <base-url> <bundle>}"
TOKEN="${CREDMGR_TOKEN:?set CREDMGR_TOKEN}"

DIR="/etc/wpa_supplicant"
DEST="$DIR/wpa_supplicant_${BUNDLE}.conf"
URL="$BASE/api/v1/bundles/$BUNDLE/render"

fp() { sha256sum "$1" | cut -c1-8; }

install -d -m 0750 -o root -g root "$DIR"
# Older versions of this script kept the ETag in a side file; it is unused now.
rm -f "$DIR/.credmgr.${BUNDLE}.etag"

INM=()
[[ -f "$DEST" ]] && INM=(-H "If-None-Match: \"$(fp "$DEST")\"")

# Download next to the destination so the final mv is atomic (the daemon may
# read the file at any moment). mktemp creates it 0600.
TMP="$(mktemp -p "$DIR" ".credmgr.${BUNDLE}.XXXXXX")"
HDR="$(mktemp)"
trap 'rm -f "$TMP" "$HDR"' EXIT

code="$(curl -sS -o "$TMP" -D "$HDR" -w '%{http_code}' \
  -H "Authorization: Bearer $TOKEN" "${INM[@]}" "$URL" || true)"

if [[ "$code" == "304" ]]; then
  echo "Render unchanged (304) - nothing to do."
  exit 0
fi
if [[ "$code" != "200" ]]; then
  echo "ERROR: pull failed with HTTP ${code:-000} ($URL)" >&2
  exit 1
fi

header() { grep -i "^$1:" "$HDR" | head -n1 | cut -d: -f2- | tr -d ' \r"'; }
expected="$(header x-render-fingerprint)"
if [[ "$(fp "$TMP")" != "$expected" ]]; then
  echo "ERROR: downloaded render does not match its fingerprint ($expected); not installing." >&2
  exit 1
fi

chown root:root "$TMP"
chmod 0600 "$TMP"
mv -f "$TMP" "$DEST"
echo "Installed $DEST (render v$(header x-render-version), fp $expected)"
echo "The pSSID daemon picks this up on its next batch run; no service restart needed."
