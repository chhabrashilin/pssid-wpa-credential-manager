#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# End-to-end smoke test (PRD 17). Walks the full user journey against a running
# stack and asserts the no-clear-text and 304 guarantees.
#
# Requires the app running with write access (SSO off + OPEN_WRITE=true, or a
# session). Point BASE at the API root.
#
#   BASE=http://localhost:8080 ./scripts/smoke.sh
# ---------------------------------------------------------------------------
set -euo pipefail

BASE="${BASE:-http://localhost:8080}"
API="$BASE/api/v1"
J="-H Content-Type:application/json"
# -k: the stack fronts itself with a self-signed certificate by default, and
# this suite asserts application behaviour, not certificate trust.
curl() { command curl -k "$@"; }
pass() { echo "  ✓ $1"; }
fail() { echo "  ✗ $1" >&2; exit 1; }

echo "== 1. Health =="
curl -fsS "$BASE/api/health" | grep -q '"status":"ok"' && pass "health ok" || fail "health"

echo "== 2. Create PEAP network =="
curl -fsS $J -X POST "$API/networks" -d '{
  "name":"smoke-mwireless","ssid":"MWireless","security":"wpa-eap-peap-mschapv2",
  "priority":5,"scan_ssid":0,"template_name":"peap-mschapv2",
  "variables":{"ca_cert":"/etc/ssl/certs/umich.pem"}}' >/dev/null && pass "network created" || fail "create network"

echo "== 3. Set credential (write-only) =="
resp="$(curl -fsS $J -X PUT "$API/networks/smoke-mwireless/credential" -d '{"identity":"pssid-probe","password":"password"}')"
echo "$resp" | grep -q '"fingerprint"' || fail "credential set"
echo "$resp" | grep -qi 'password' && fail "response leaked password field" || pass "credential set, no value returned"

echo "== 4. GET network never returns a secret =="
curl -fsS "$API/networks/smoke-mwireless" | grep -qi '"password"' && fail "network GET leaked secret" || pass "no secret in GET"

echo "== 5. Bundle + render =="
curl -fsS $J -X POST "$API/bundles" -d '{"name":"smoke-bundle","network_names":["smoke-mwireless"]}' >/dev/null && pass "bundle created" || fail "bundle"
curl -fsS $J -X POST "$API/bundles/smoke-bundle/render" >/dev/null && pass "rendered" || fail "render"

echo "== 6. Preview is redacted =="
prev="$(curl -fsS "$API/bundles/smoke-bundle/preview")"
echo "$prev" | grep -q 'redacted' && pass "preview redacted" || fail "preview not redacted"

echo "== 7. Create machine token =="
tokresp="$(curl -fsS $J -X POST "$API/tokens" -d '{"name":"smoke","scopes":["smoke-bundle"],"expires_in_days":1}')"
tok="$(echo "$tokresp" | sed -n 's/.*"token":"\([^"]*\)".*/\1/p')"
tokid="$(echo "$tokresp" | sed -n 's/.*"id":"\([^"]*\)".*/\1/p')"
[[ -n "$tok" ]] && pass "token issued" || fail "token"

echo "== 8. Pull render (200) - hash form, no clear text =="
hdr="$(mktemp)"; body="$(curl -fsS -D "$hdr" -H "Authorization: Bearer $tok" "$API/bundles/smoke-bundle/render")"
echo "$body" | grep -q 'password=hash:8846f7eaee8fb117ad06bdd830b7586c' && pass "NT hash form present" || fail "hash form missing"
if echo "$body" | grep -E 'password=' | grep -qv 'password=hash:'; then fail "clear password present"; else pass "no clear password"; fi
grep -qi 'cache-control: no-store' "$hdr" && pass "no-store header" || fail "missing no-store"
etag="$(grep -i '^etag:' "$hdr" | awk '{print $2}' | tr -d '\r')"

echo "== 9. Re-pull with If-None-Match -> 304 =="
code="$(curl -fsS -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $tok" -H "If-None-Match: $etag" "$API/bundles/smoke-bundle/render")"
[[ "$code" == "304" ]] && pass "304 no-op" || fail "expected 304 got $code"

echo "== 10. Rotate credential -> new render -> pull picks it up =="
curl -fsS $J -X PUT "$API/networks/smoke-mwireless/credential" -d '{"identity":"pssid-probe","password":"welcome"}' >/dev/null
curl -fsS $J -X POST "$API/bundles/smoke-bundle/render" >/dev/null
new="$(curl -fsS -H "Authorization: Bearer $tok" "$API/bundles/smoke-bundle/render")"
echo "$new" | grep -q 'password=hash:674e48b68c5cd0efd8f7e5faa87b3d1e' && pass "rotation reflected in pull" || fail "rotation not reflected"

echo "== 11. Audit shows the pull and rotate =="
curl -fsS "$API/audit?action=render.pull" | grep -q 'render.pull' && pass "audit render.pull" || fail "audit"

echo "== Cleanup (order matters: revoke token, then bundle, then network) =="
curl -fsS -X DELETE "$API/tokens/$tokid" >/dev/null
curl -fsS -X DELETE "$API/bundles/smoke-bundle" >/dev/null
curl -fsS -X DELETE "$API/networks/smoke-mwireless" >/dev/null
pass "cleaned up"

echo
echo "ALL SMOKE CHECKS PASSED"
