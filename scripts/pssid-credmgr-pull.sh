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
# If-None-Match is computed from the installed file itself: a deleted or
# hand-edited file simply gets pulled again.
#
# Beside the config it leaves .credmgr.<bundle>.etag holding that fingerprint.
# Nothing here reads it back. It is a marker for pssid-probe-health, whose
# credmgr.sync check uses it to tell a profile this tool delivered from one
# copied to the probe some other way.
#
#   CREDMGR_TOKEN=xxx ./pssid-credmgr-pull.sh \
#     https://credmgr.example.edu eduroam
# ---------------------------------------------------------------------------
set -euo pipefail

BASE="${1:?usage: pssid-credmgr-pull.sh <base-url> <bundle>}"
BUNDLE="${2:?usage: pssid-credmgr-pull.sh <base-url> <bundle>}"
TOKEN="${CREDMGR_TOKEN:?set CREDMGR_TOKEN}"

# The bundle name becomes part of a URL and of a file name under /etc, so it
# must be a plain name. This is the rule pssid-daemon applies to the SSID
# profile name the file is read back under.
if [[ ! "$BUNDLE" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$ ]]; then
  echo "ERROR: bundle name '$BUNDLE' must be letters, digits, '.', '_' or '-' (it names the config file)." >&2
  exit 2
fi

DIR="/etc/wpa_supplicant"
DEST="$DIR/wpa_supplicant_${BUNDLE}.conf"
MARKER="$DIR/.credmgr.${BUNDLE}.etag"
URL="${BASE%/}/api/v1/bundles/$BUNDLE/render"

fp() { sha256sum "$1" | cut -c1-8; }
# Record the fingerprint of what is installed (0600: the directory listing
# already says which networks the probe has, the marker adds nothing secret).
mark() { ( umask 077; printf '%s\n' "$1" > "$MARKER.tmp" ) && mv -f "$MARKER.tmp" "$MARKER"; }

install -d -m 0750 -o root -g root "$DIR"

INM=()
[[ -f "$DEST" ]] && INM=(-H "If-None-Match: \"$(fp "$DEST")\"")

# Download next to the destination so the final mv is atomic (the daemon may
# read the file at any moment). mktemp creates it 0600.
TMP="$(mktemp -p "$DIR" ".credmgr.${BUNDLE}.XXXXXX")"
HDR="$(mktemp)"
trap 'rm -f "$TMP" "$HDR" "$MARKER.tmp"' EXIT

# Deadlines, so a pull run from cron cannot hang on an unreachable manager.
code="$(curl -sS --connect-timeout 10 --max-time 60 -o "$TMP" -D "$HDR" -w '%{http_code}' \
  -H "Authorization: Bearer $TOKEN" "${INM[@]}" "$URL" || true)"

if [[ "$code" == "304" ]]; then
  mark "$(fp "$DEST")"
  echo "Render unchanged (304) - nothing to do."
  exit 0
fi
if [[ "$code" != "200" ]]; then
  echo "ERROR: pull failed with HTTP ${code:-000} ($URL)" >&2
  exit 1
fi

# "|| true": a header that is absent is an empty value to report below, not a
# silent exit under "set -e -o pipefail".
header() { { grep -i "^$1:" "$HDR" || true; } | head -n1 | cut -d: -f2- | tr -d ' \r"'; }
expected="$(header x-render-fingerprint)"
if [[ -z "$expected" || "$(fp "$TMP")" != "$expected" ]]; then
  echo "ERROR: downloaded render does not match its fingerprint (${expected:-header missing}); not installing." >&2
  exit 1
fi

chown root:root "$TMP"
chmod 0600 "$TMP"
mv -f "$TMP" "$DEST"
mark "$expected"
version="$(header x-render-version)"
echo "Installed $DEST (render v${version:-?}, fp $expected)"
echo "The pSSID daemon picks this up on its next batch run; no service restart needed."
