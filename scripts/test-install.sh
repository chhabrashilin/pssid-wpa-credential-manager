#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Installer regression suite — exercises install.sh WITHOUT Docker.
#
# install.sh is the one script every operator runs and the one script the
# end-to-end CI job depends on, but it was only ever tested by running it for
# real: a full image build against a live daemon. That is slow enough that its
# argument handling went untested, which is how the interactive hostname prompt
# became unreachable dead code (bash sets $HOSTNAME itself, so the "was it
# provided?" test was always true) without anything noticing.
#
# This runs the real install.sh against stub `docker` and `curl` binaries and
# asserts on what it produces: the .env, the KEK, the file modes, the exit code.
# Seconds, no daemon, no network.
#
#   bash scripts/test-install.sh
# ---------------------------------------------------------------------------
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALLER="$REPO_ROOT/install.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PASS=0
FAIL=0
pass() { printf '  \033[32mok\033[0m   %s\n' "$1"; PASS=$((PASS + 1)); }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAIL=$((FAIL + 1)); }

check() { # check <description> <expected> <actual>
  if [[ "$2" == "$3" ]]; then pass "$1"; else
    fail "$1"
    printf '         expected: %s\n         actual:   %s\n' "$2" "$3"
  fi
}

# --- Stub toolchain --------------------------------------------------------
# `docker` accepts everything. `curl` reports healthy unless STUB_UNHEALTHY=1,
# which lets us test the failure path without breaking anything.
mkdir -p "$WORK/bin"
cat > "$WORK/bin/docker" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
cat > "$WORK/bin/curl" <<'EOF'
#!/usr/bin/env bash
[[ "${STUB_UNHEALTHY:-0}" == "1" ]] && exit 7
echo '{"status":"ok","db":true,"kek":true}'
EOF
chmod +x "$WORK/bin/docker" "$WORK/bin/curl"

# --- Scenario harness ------------------------------------------------------
# Each scenario gets a pristine copy of the installer and its inputs, so no
# scenario can be contaminated by a previous one's .env or master.key.
setup_scenario() { # setup_scenario <name> -> echoes the scenario dir
  local dir="$WORK/$1"
  mkdir -p "$dir/config"
  cp "$INSTALLER" "$dir/install.sh"
  chmod +x "$dir/install.sh"
  [[ -f "$REPO_ROOT/config/roles.example.json" ]] &&
    cp "$REPO_ROOT/config/roles.example.json" "$dir/config/"
  echo "$dir"
}

run_installer() { # run_installer <dir> [env assignments...] -- captures rc
  local dir="$1"; shift
  # A 2s health budget keeps the suite fast; the stub answers instantly, and
  # the unhealthy scenario only needs one failed attempt to prove its point.
  ( cd "$dir" && PATH="$WORK/bin:$PATH" env HEALTH_TIMEOUT_SECS=2 "$@" ./install.sh -y ) \
    >"$dir/stdout.log" 2>"$dir/stderr.log"
}

envval() { # envval <dir> <KEY>
  grep -E "^$2=" "$1/.env" 2>/dev/null | head -1 | cut -d= -f2-
}

echo "== install.sh regression suite =="
echo

# --- 1. The documented non-interactive interface still works ---------------
# This is the exact invocation in .github/workflows/ci.yml and README.md.
echo "1. HOSTNAME=<x> ./install.sh -y  (documented CI interface)"
d="$(setup_scenario ci-interface)"
run_installer "$d" HOSTNAME=localhost TLS=none SSO=false
rc=$?
check "exits 0" "0" "$rc"
check "BASE_URL uses the supplied hostname" "https://localhost" "$(envval "$d" BASE_URL)"
check "SSO_ENABLED propagated" "false" "$(envval "$d" SSO_ENABLED)"
check "OPEN_WRITE defaults closed" "false" "$(envval "$d" OPEN_WRITE)"
echo

# --- 2. CREDMGR_HOSTNAME is the explicit override --------------------------
echo "2. CREDMGR_HOSTNAME overrides"
d="$(setup_scenario explicit-hostname)"
run_installer "$d" CREDMGR_HOSTNAME=credmgr.example.edu TLS=none SSO=false
check "BASE_URL uses CREDMGR_HOSTNAME" "https://credmgr.example.edu" "$(envval "$d" BASE_URL)"
echo

# --- 3. Explicit override beats the $HOSTNAME suggestion -------------------
# The regression that motivated this file: $HOSTNAME is always set by bash, so
# it must never be able to win over a value the operator actually chose.
echo "3. CREDMGR_HOSTNAME wins over an inherited HOSTNAME"
d="$(setup_scenario override-precedence)"
run_installer "$d" CREDMGR_HOSTNAME=chosen.example.edu HOSTNAME=machine-name TLS=none SSO=false
check "the chosen name wins" "https://chosen.example.edu" "$(envval "$d" BASE_URL)"
echo

# --- 4. Secrets are generated correctly ------------------------------------
echo "4. Master key and .env permissions"
d="$(setup_scenario secrets)"
run_installer "$d" HOSTNAME=localhost TLS=none SSO=false
if [[ -f "$d/secrets/master.key" ]]; then
  pass "master.key created"
  size="$(wc -c < "$d/secrets/master.key" | tr -d ' ')"
  check "master.key is exactly 32 bytes" "32" "$size"
else
  fail "master.key created"
fi
# Mode checks only mean something on a filesystem that has modes.
if [[ "$(uname -s)" == Linux* || "$(uname -s)" == Darwin* ]]; then
  check ".env is 0600" "600" "$(stat -c '%a' "$d/.env" 2>/dev/null || stat -f '%Lp' "$d/.env")"
  check "master.key is 0400" "400" "$(stat -c '%a' "$d/secrets/master.key" 2>/dev/null || stat -f '%Lp' "$d/secrets/master.key")"
else
  echo "  skip file-mode checks (not a POSIX filesystem)"
fi
check "KEK_FILE points at the mounted path" "/run/secrets/master.key" "$(envval "$d" KEK_FILE)"
echo

# --- 5. Re-running is idempotent -------------------------------------------
# An operator re-running the installer to pick up a new image must not get a
# fresh KEK: that silently orphans every stored secret.
echo "5. Re-running preserves the existing KEK and .env"
d="$(setup_scenario idempotent)"
run_installer "$d" HOSTNAME=localhost TLS=none SSO=false
kek_before="$(sha256sum "$d/secrets/master.key" 2>/dev/null | cut -d' ' -f1)"
env_before="$(sha256sum "$d/.env" 2>/dev/null | cut -d' ' -f1)"
run_installer "$d" HOSTNAME=localhost TLS=none SSO=false
rc=$?
check "second run exits 0" "0" "$rc"
check "master.key unchanged" "$kek_before" "$(sha256sum "$d/secrets/master.key" 2>/dev/null | cut -d' ' -f1)"
check ".env unchanged" "$env_before" "$(sha256sum "$d/.env" 2>/dev/null | cut -d' ' -f1)"
echo

# --- 6. An unhealthy stack is reported as a failure ------------------------
# Containers up + API dead must not print "Done" and exit 0.
echo "6. Unhealthy stack fails loudly"
d="$(setup_scenario unhealthy)"
run_installer "$d" HOSTNAME=localhost TLS=none SSO=false STUB_UNHEALTHY=1
rc=$?
check "exits non-zero" "1" "$rc"
if grep -q "never became healthy" "$d/stdout.log"; then
  pass "explains what went wrong"
else
  fail "explains what went wrong"
fi
if grep -q "docker compose logs" "$d/stdout.log"; then
  pass "points at the next diagnostic step"
else
  fail "points at the next diagnostic step"
fi
echo

# --- 7. Self-signed certificate generation ---------------------------------
if command -v openssl >/dev/null 2>&1; then
  echo "7. TLS=self-signed generates a certificate for the chosen hostname"
  d="$(setup_scenario tls)"
  run_installer "$d" CREDMGR_HOSTNAME=certtest.example.edu TLS=self-signed SSO=false MSYS_NO_PATHCONV=1
  if [[ -f "$d/certs/fullchain.pem" ]]; then
    pass "certificate created"
    subj="$(openssl x509 -in "$d/certs/fullchain.pem" -noout -subject 2>/dev/null)"
    # The CN must be the hostname the operator chose, not the build machine's.
    if grep -q "certtest.example.edu" <<<"$subj"; then
      pass "certificate CN matches the chosen hostname"
    else
      fail "certificate CN matches the chosen hostname"
      printf '         subject: %s\n' "$subj"
    fi
  else
    fail "certificate created"
  fi
  echo
else
  echo "7. skipped (openssl not available)"
  echo
fi

# --- Result ----------------------------------------------------------------
echo "-----------------------------------------"
printf 'passed: %d   failed: %d\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]] || exit 1
echo "installer suite green"
