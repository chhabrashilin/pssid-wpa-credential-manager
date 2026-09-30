#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Run every project's suite and report one summary.
#
#   ./run-all.sh            # all suites
#   ./run-all.sh --demo     # also run the demos
#
# Requires bash, git, python3 (3.9+) and jinja2. No other third-party packages.
# ---------------------------------------------------------------------------
set -uo pipefail
cd "$(dirname "$0")"

if [[ -t 1 ]] && [[ -z "${NO_COLOR:-}" ]]; then
  RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; BLD=$'\033[1m'; DIM=$'\033[2m'; OFF=$'\033[0m'
else
  RED=''; GRN=''; YEL=''; BLD=''; DIM=''; OFF=''
fi

DEMO=false
[[ "${1:-}" == "--demo" ]] && DEMO=true

PYTHON="${PYTHON:-python3}"
FAILED=()
PASSED=()
SKIPPED=()

section() { printf '\n%s%s%s\n%s\n' "$BLD" "$1" "$OFF" "$(printf '=%.0s' $(seq 1 ${#1}))"; }

record() { # record <name> <rc>
  if [[ "$2" -eq 0 ]]; then PASSED+=("$1"); else FAILED+=("$1"); fi
}

# --- Preflight -------------------------------------------------------------
section "Preflight"
missing=false
for tool in bash git "$PYTHON"; do
  if command -v "$tool" >/dev/null 2>&1; then
    printf '  %sok%s   %s\n' "$GRN" "$OFF" "$tool"
  else
    printf '  %sXX%s   %s not found\n' "$RED" "$OFF" "$tool"; missing=true
  fi
done
if "$PYTHON" -c "import jinja2" 2>/dev/null; then
  printf '  %sok%s   jinja2\n' "$GRN" "$OFF"
else
  printf '  %s!!%s   jinja2 missing (pssid-daemon-tests will be skipped)\n' "$YEL" "$OFF"
fi
$missing && { echo "Missing required tools; aborting." >&2; exit 2; }

# --- 1. repo-hygiene -------------------------------------------------------
section "repo-hygiene"
bash repo-hygiene/self-test.sh
record "repo-hygiene self-test" $?

echo
echo "${DIM}Checking this repository...${OFF}"
bash repo-hygiene/check-repo-hygiene.sh ..
record "repo-hygiene check (this repo)" $?

# --- 2. pssid-daemon-tests -------------------------------------------------
section "pssid-daemon-tests"
if ! "$PYTHON" -c "import jinja2" 2>/dev/null; then
  printf '  %sskipped%s -- jinja2 not installed\n' "$YEL" "$OFF"
  SKIPPED+=("pssid-daemon-tests (no jinja2)")
elif ! ( cd pssid-daemon-tests && "$PYTHON" -c "from harness import loader; loader.daemon_path()" 2>/dev/null ); then
  printf '  %sskipped%s -- pssid-daemon.py not found beside this repo\n' "$YEL" "$OFF"
  printf '  %sset PSSID_DAEMON_PATH to run these%s\n' "$DIM" "$OFF"
  SKIPPED+=("pssid-daemon-tests (daemon not found)")
else
  ( cd pssid-daemon-tests && ./run-tests.sh )
  record "pssid-daemon-tests" $?
fi

# --- 3. pssid-probe-health -------------------------------------------------
section "pssid-probe-health"
( cd pssid-probe-health && ./run-tests.sh )
record "pssid-probe-health" $?

if $DEMO; then
  section "pssid-probe-health demo"
  ( cd pssid-probe-health && bash demo.sh )
  record "pssid-probe-health demo" $?
fi

# --- 4. docs-content -------------------------------------------------------
section "docs-content"
docs_ok=0
for f in docs-content/*.md; do
  [[ -f "$f" ]] || continue
  if [[ -s "$f" ]] && head -1 "$f" | grep -q '^# '; then
    printf '  %sok%s   %s (%s lines)\n' "$GRN" "$OFF" "$(basename "$f")" "$(wc -l < "$f" | tr -d ' ')"
  else
    printf '  %sXX%s   %s is empty or has no title\n' "$RED" "$OFF" "$(basename "$f")"
    docs_ok=1
  fi
done
record "docs-content" $docs_ok

# --- 5. datapipeline-investigation -----------------------------------------
section "datapipeline-investigation"
if [[ -s datapipeline-investigation/README.md ]]; then
  printf '  %sok%s   investigation present (%s lines) -- specification, not code by design\n' \
    "$GRN" "$OFF" "$(wc -l < datapipeline-investigation/README.md | tr -d ' ')"
  record "datapipeline-investigation" 0
else
  printf '  %sXX%s   missing\n' "$RED" "$OFF"
  record "datapipeline-investigation" 1
fi

# --- Summary ---------------------------------------------------------------
section "Summary"
for p in "${PASSED[@]}";  do printf '  %spass%s    %s\n' "$GRN" "$OFF" "$p"; done
for s in "${SKIPPED[@]:-}"; do [[ -n "$s" ]] && printf '  %sskip%s    %s\n' "$YEL" "$OFF" "$s"; done
for f in "${FAILED[@]:-}";  do [[ -n "$f" ]] && printf '  %sFAIL%s    %s\n' "$RED" "$OFF" "$f"; done

echo
printf 'passed: %d   failed: %d   skipped: %d\n' \
  "${#PASSED[@]}" "${#FAILED[@]}" "${#SKIPPED[@]}"

[[ ${#FAILED[@]} -eq 0 ]] || exit 1
printf '%sall green%s\n' "$GRN" "$OFF"
