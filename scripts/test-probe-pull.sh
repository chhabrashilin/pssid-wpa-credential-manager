#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Probe-pull regression suite. Runs the two real probe-side pull tools,
# scripts/pssid-credmgr-pull.sh and ansible/probe-pull-example.yml, against a
# running stack on THIS machine and asserts what lands in /etc/wpa_supplicant:
# the file name the pSSID daemon opens, 0600 root, a 304 no-op on re-run, and
# recovery when the installed file is deleted or edited.
#
# Needs root (it writes /etc/wpa_supplicant) and ansible-playbook. The app
# must allow writes (SSO off + OPEN_WRITE=true), like scripts/smoke.sh.
#
#   sudo BASE=https://localhost bash scripts/test-probe-pull.sh
# ---------------------------------------------------------------------------
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE="${BASE:-https://localhost}"
API="$BASE/api/v1"
J="-H Content-Type:application/json"
NAME="probe-pull-test"
DEST="/etc/wpa_supplicant/wpa_supplicant_${NAME}.conf"
# The marker pssid-probe-health's credmgr.sync check looks for.
MARKER="/etc/wpa_supplicant/.credmgr.${NAME}.etag"
# The stack's self-signed certificate is the trust anchor for the shell helper
# (curl reads CURL_CA_BUNDLE); this suite asserts delivery, not PKI.
export CURL_CA_BUNDLE="${CURL_CA_BUNDLE:-$REPO_ROOT/certs/fullchain.pem}"

# -k for this suite's own API calls only; the tools under test verify TLS.
curl() { command curl -k "$@"; }
pass() { echo "  ✓ $1"; }
fail() { echo "  ✗ $1" >&2; exit 1; }
[[ $EUID -eq 0 ]] || fail "run as root (writes /etc/wpa_supplicant)"
command -v ansible-playbook >/dev/null || fail "ansible-playbook not found"

WORK="$(mktemp -d)"
tokid=""
cleanup() {
  [[ -n "$tokid" ]] && curl -fsS -X DELETE "$API/tokens/$tokid" >/dev/null || true
  curl -fsS -X DELETE "$API/bundles/$NAME" >/dev/null || true
  curl -fsS -X DELETE "$API/networks/$NAME" >/dev/null || true
  rm -rf "$WORK" "$DEST" "$MARKER"
}
trap cleanup EXIT

render() { curl -fsS $J -X POST "$API/bundles/$NAME/render" >/dev/null; }
fp() { sha256sum "$1" | cut -c1-8; }
served_fp() { curl -fsS -D - -o /dev/null -H "Authorization: Bearer $tok" "$API/bundles/$NAME/render" \
  | grep -i '^x-render-fingerprint:' | cut -d: -f2 | tr -d ' \r'; }
check_installed() {
  [[ -f "$DEST" ]] || fail "$DEST missing"
  [[ "$(stat -c '%a %U %G' "$DEST")" == "600 root root" ]] || fail "$DEST is $(stat -c '%a %U %G' "$DEST"), want 600 root root"
  [[ "$(fp "$DEST")" == "$(served_fp)" ]] || fail "$DEST does not match the current render"
  grep -q '^\s*psk=[0-9a-f]\{64\}$' "$DEST" || fail "$DEST has no derived psk= line"
  [[ "$(cat "$MARKER" 2>/dev/null)" == "$(fp "$DEST")" ]] || fail "$MARKER does not hold the installed file's fingerprint"
  [[ "$(stat -c '%a %U %G' "$MARKER")" == "600 root root" ]] || fail "$MARKER is $(stat -c '%a %U %G' "$MARKER"), want 600 root root"
  pass "$1"
}

echo "== Setup: PSK network, one-network bundle, render, scoped token =="
curl -fsS $J -X POST "$API/networks" -d "{\"name\":\"$NAME\",\"ssid\":\"ProbePullTest\",
  \"security\":\"wpa-psk\",\"priority\":1,\"scan_ssid\":0,\"template_name\":\"wpa-psk\",\"variables\":{}}" >/dev/null
curl -fsS $J -X PUT "$API/networks/$NAME/credential" -d '{"passphrase":"probe-pull-one"}' >/dev/null
curl -fsS $J -X POST "$API/bundles" -d "{\"name\":\"$NAME\",\"network_names\":[\"$NAME\"]}" >/dev/null
render
tokresp="$(curl -fsS $J -X POST "$API/tokens" -d "{\"name\":\"$NAME\",\"scopes\":[\"$NAME\"],\"expires_in_days\":1}")"
tok="$(echo "$tokresp" | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')"
tokid="$(echo "$tokresp" | sed -n 's/.*"id":"\([^"]*\)".*/\1/p')"
[[ -n "$tok" ]] && pass "setup done" || fail "token not issued"
rm -f "$DEST"

echo "== Shell helper: scripts/pssid-credmgr-pull.sh =="
helper() { CREDMGR_TOKEN="$tok" bash "$REPO_ROOT/scripts/pssid-credmgr-pull.sh" "$BASE" "$NAME"; }
helper | grep -q '^Installed' || fail "first pull did not install"
check_installed "first pull installs the daemon's per-profile file"
helper | grep -q '(304)' || fail "re-pull was not a 304"
pass "unchanged render is a 304 no-op"
# The marker stays behind on purpose: it must never stand in for the file.
rm -f "$DEST"
helper | grep -q '^Installed' || fail "deleted file was not restored"
check_installed "deleted file is restored (a leftover marker does not cause a 304)"
rm -f "$MARKER"
helper | grep -q '(304)' || fail "re-pull after losing the marker was not a 304"
check_installed "a 304 puts a missing marker back"
if CREDMGR_TOKEN="$tok" bash "$REPO_ROOT/scripts/pssid-credmgr-pull.sh" "$BASE" "../$NAME" 2>/dev/null; then
  fail "a bundle name with a path in it was accepted"
fi
pass "a bundle name that is not a plain name is refused"
echo "# local edit" >> "$DEST"
helper | grep -q '^Installed' || fail "edited file was not replaced"
check_installed "hand-edited file is replaced"
curl -fsS $J -X PUT "$API/networks/$NAME/credential" -d '{"passphrase":"probe-pull-two"}' >/dev/null
render
helper | grep -q '^Installed' || fail "rotated render was not installed"
check_installed "rotated credential is picked up"
if CREDMGR_TOKEN="credmgr_not-a-real-token" bash "$REPO_ROOT/scripts/pssid-credmgr-pull.sh" "$BASE" "$NAME" 2>/dev/null; then
  fail "bad token did not fail"
fi
check_installed "bad token fails and leaves the installed file alone"

echo "== Ansible: ansible/probe-pull-example.yml =="
printf '[probes]\nlocalhost ansible_connection=local ansible_python_interpreter=auto_silent\n' > "$WORK/inv.ini"
play() {
  ANSIBLE_NOCOLOR=1 ansible-playbook -i "$WORK/inv.ini" "$REPO_ROOT/ansible/probe-pull-example.yml" \
    -e "credmgr_base=$BASE" -e "{\"credmgr_bundles\": [\"$NAME\"]}" \
    -e "credmgr_token=$tok" -e credmgr_validate_certs=false > "$WORK/play.log" 2>&1 \
    || { cat "$WORK/play.log" >&2; fail "playbook failed"; }
  grep -o 'changed=[0-9]*' "$WORK/play.log" | tail -n1 | cut -d= -f2
}
rm -f "$DEST" "$MARKER"
[[ "$(play)" != "0" ]] || fail "first run did not report changed"
check_installed "first run installs the daemon's per-profile file"
grep -q "$tok" "$WORK/play.log" && fail "token leaked into playbook output"
[[ "$(play)" == "0" ]] || fail "re-run reported changed"
pass "re-run is a 304 no-op (changed=0)"
before="$(stat -c %Y "$DEST")"
sleep 1; play >/dev/null
[[ "$(stat -c %Y "$DEST")" == "$before" ]] || fail "re-run rewrote the file"
pass "re-run leaves the file untouched"
echo "# local edit" >> "$DEST"
[[ "$(play)" != "0" ]] || fail "edited file was not replaced"
check_installed "hand-edited file is replaced"
curl -fsS $J -X PUT "$API/networks/$NAME/credential" -d '{"passphrase":"probe-pull-three"}' >/dev/null
render
[[ "$(play)" != "0" ]] || fail "rotated render was not installed"
check_installed "rotated credential is picked up"

echo
echo "ALL PROBE-PULL CHECKS PASSED"
