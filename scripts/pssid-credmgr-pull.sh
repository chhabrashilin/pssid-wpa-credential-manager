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
#   CREDMGR_TOKEN=xxx ./pssid-credmgr-pull.sh \
#     https://credmgr.example.edu eduroam
# ---------------------------------------------------------------------------
set -euo pipefail

BASE="${1:?usage: pssid-credmgr-pull.sh <base-url> <bundle>}"
BUNDLE="${2:?usage: pssid-credmgr-pull.sh <base-url> <bundle>}"
TOKEN="${CREDMGR_TOKEN:?set CREDMGR_TOKEN}"

DEST="/etc/wpa_supplicant/wpa_supplicant_${BUNDLE}.conf"
ETAG_FILE="/etc/wpa_supplicant/.credmgr.${BUNDLE}.etag"
URL="$BASE/api/v1/bundles/$BUNDLE/render"

install -d -m 0750 -o root -g root /etc/wpa_supplicant

INM=()
[[ -f "$ETAG_FILE" ]] && INM=(-H "If-None-Match: $(cat "$ETAG_FILE")")

TMP="$(mktemp)"
HDR="$(mktemp)"
trap 'rm -f "$TMP" "$HDR"' EXIT

code="$(curl -fsS -o "$TMP" -D "$HDR" -w '%{http_code}' \
  -H "Authorization: Bearer $TOKEN" "${INM[@]}" "$URL" || true)"

if [[ "$code" == "304" ]]; then
  echo "Render unchanged (304) - nothing to do."
  exit 0
fi
if [[ "$code" != "200" ]]; then
  echo "ERROR: pull failed with HTTP $code" >&2
  exit 1
fi

install -m 0600 -o root -g root "$TMP" "$DEST"
grep -i '^etag:' "$HDR" | awk '{print $2}' | tr -d '\r' > "$ETAG_FILE" || true
echo "Installed $DEST ($(grep -i '^x-render-version' "$HDR" | tr -d '\r'))"
echo "The pSSID daemon picks this up on its next batch run; no service restart needed."
