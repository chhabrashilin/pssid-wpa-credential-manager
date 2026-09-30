#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# self-test — prove the checker detects what it claims to, and stays quiet
# about what it should not.
#
# A linter is only worth running if its false-positive rate is known. This
# builds throwaway repositories with known-good and known-bad content and
# asserts the verdict on each.
#
#   ./self-test.sh
# ---------------------------------------------------------------------------
set -uo pipefail
cd "$(dirname "$0")"

CHECKER="$PWD/check-repo-hygiene.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

PASS=0
FAIL=0
pass() { printf '  \033[32mok\033[0m   %s\n' "$1"; PASS=$((PASS + 1)); }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAIL=$((FAIL + 1)); }

# Build a scratch repository. Anything after the name is a "path:mode" pair.
make_repo() { # make_repo <name>
  local dir="$WORK/$1"
  mkdir -p "$dir"
  git -C "$dir" init -q 2>/dev/null
  git -C "$dir" config user.email t@example.com
  git -C "$dir" config user.name Test
  printf '*.sh text eol=lf\n' > "$dir/.gitattributes"
  echo "$dir"
}

commit() { # commit <dir>
  git -C "$1" add -A 2>/dev/null
  git -C "$1" commit -qm test 2>/dev/null
}

run_checker() { # run_checker <dir> -> stdout, sets RC
  NO_COLOR=1 bash "$CHECKER" "$1" 2>&1
}

assert_flags() { # assert_flags <desc> <dir> <needle>
  local out; out="$(run_checker "$2")"
  if grep -q "ERROR.*$3" <<<"$out"; then pass "$1"; else
    fail "$1"
    printf '       expected an ERROR mentioning %s\n' "$3"
    sed 's/^/       | /' <<<"$out" | head -12
  fi
}

assert_clean_for() { # assert_clean_for <desc> <dir> <needle>
  local out; out="$(run_checker "$2")"
  if grep -q "ERROR.*$3" <<<"$out"; then
    fail "$1"
    printf '       FALSE POSITIVE on %s\n' "$3"
    sed 's/^/       | /' <<<"$out" | head -12
  else pass "$1"; fi
}

echo "== repo-hygiene self-test =="
echo

# --- 1. The bug that started this --------------------------------------
echo "1. Executable bit"
d="$(make_repo direct-invocation)"
printf '#!/usr/bin/env bash\necho hi\n' > "$d/install.sh"
printf '# Setup\n\nRun it:\n\n```bash\n./install.sh -y\n```\n' > "$d/README.md"
commit "$d"
git -C "$d" update-index --chmod=-x install.sh 2>/dev/null
assert_flags "flags a 100644 script documented as ./install.sh" "$d" "install.sh"

d="$(make_repo sudo-invocation)"
mkdir -p "$d/scripts"
printf '#!/usr/bin/env bash\necho hi\n' > "$d/scripts/provision.sh"
printf 'Deliver config:\n\n    sudo scripts/provision.sh --limit rpi4\n' > "$d/README.md"
commit "$d"
git -C "$d" update-index --chmod=-x scripts/provision.sh 2>/dev/null
assert_flags "flags a 100644 script documented as sudo scripts/x.sh" "$d" "provision.sh"

d="$(make_repo already-executable)"
printf '#!/usr/bin/env bash\necho hi\n' > "$d/install.sh"
printf 'Run `./install.sh`\n' > "$d/README.md"
chmod +x "$d/install.sh"
commit "$d"
git -C "$d" update-index --chmod=+x install.sh 2>/dev/null
assert_clean_for "accepts a correctly-executable script" "$d" "install.sh"
echo

# --- 2. False positives, calibrated against the real repos --------------
echo "2. Must NOT flag (these are correct at 100644)"
d="$(make_repo sourced-library)"
mkdir -p "$d/scripts/lib"
printf '#!/usr/bin/env bash\ncheck_disk() { :; }\n' > "$d/scripts/lib/preflight.sh"
printf '#!/usr/bin/env bash\nsource scripts/lib/preflight.sh\n' > "$d/install.sh"
printf 'See `scripts/lib/preflight.sh` for the disk check.\n' > "$d/README.md"
commit "$d"
assert_clean_for "ignores a sourced library" "$d" "preflight.sh"

d="$(make_repo bash-invoked)"
mkdir -p "$d/scripts"
printf '#!/usr/bin/env bash\necho seed\n' > "$d/scripts/seed.sh"
printf 'seed:\n\t@bash scripts/seed.sh\n' > "$d/Makefile"
printf 'Run `make seed` ([`scripts/seed.sh`](scripts/seed.sh)).\n' > "$d/README.md"
commit "$d"
assert_clean_for "ignores a script only ever run as 'bash scripts/x.sh'" "$d" "seed.sh"

d="$(make_repo markdown-relative-link)"
mkdir -p "$d/docs" "$d/scripts"
printf '#!/usr/bin/env bash\necho hi\n' > "$d/scripts/tool.sh"
# The `../scripts/tool.sh` here contains "./scripts/tool.sh" as a substring --
# the exact false positive that killed the first version of the detector.
printf 'See [the tool](../scripts/tool.sh) for details.\n' > "$d/docs/guide.md"
commit "$d"
assert_clean_for "ignores ./ inside a relative markdown link" "$d" "tool.sh"
echo

# --- 3. CRLF -------------------------------------------------------------
echo "3. Line endings"
d="$(make_repo crlf)"
rm -f "$d/.gitattributes"   # no guard, so CRLF survives into the index
printf '#!/usr/bin/env bash\r\necho hi\r\n' > "$d/tool.sh"
commit "$d"
out="$(run_checker "$d")"
if grep -q "CRLF" <<<"$out"; then pass "flags CRLF line endings in the index"; else
  fail "flags CRLF line endings in the index"; sed 's/^/       | /' <<<"$out" | head -10
fi

d="$(make_repo lf-clean)"
printf '#!/usr/bin/env bash\necho hi\n' > "$d/tool.sh"
commit "$d"
out="$(run_checker "$d")"
if grep -q "ERROR.*CRLF" <<<"$out"; then
  fail "accepts LF endings"; sed 's/^/       | /' <<<"$out" | head -10
else pass "accepts LF endings"; fi
echo

# --- 4. Other checks -----------------------------------------------------
echo "4. Syntax, shebang, .gitattributes"
d="$(make_repo broken-syntax)"
printf '#!/usr/bin/env bash\nif [ 1 -eq 1 ]; then\n  echo unterminated\n' > "$d/bad.sh"
commit "$d"
out="$(run_checker "$d")"
if grep -q "does not parse" <<<"$out"; then pass "flags a script that does not parse"; else
  fail "flags a script that does not parse"; sed 's/^/       | /' <<<"$out" | head -10
fi

d="$(make_repo no-shebang)"
printf 'echo hi\n' > "$d/tool.sh"
commit "$d"
out="$(run_checker "$d")"
if grep -q "no shebang" <<<"$out"; then pass "warns about a missing shebang"; else
  fail "warns about a missing shebang"; sed 's/^/       | /' <<<"$out" | head -10
fi

d="$(make_repo no-gitattributes)"
rm -f "$d/.gitattributes"
printf '#!/usr/bin/env bash\necho hi\n' > "$d/tool.sh"
commit "$d"
out="$(run_checker "$d")"
if grep -q "no .gitattributes" <<<"$out"; then pass "warns about a missing .gitattributes"; else
  fail "warns about a missing .gitattributes"; sed 's/^/       | /' <<<"$out" | head -10
fi
echo

# --- 5. Exit codes -------------------------------------------------------
echo "5. Exit codes"
d="$(make_repo exit-dirty)"
printf '#!/usr/bin/env bash\necho hi\n' > "$d/install.sh"
printf 'Run `./install.sh`\n' > "$d/README.md"
commit "$d"
git -C "$d" update-index --chmod=-x install.sh 2>/dev/null
NO_COLOR=1 bash "$CHECKER" "$d" >/dev/null 2>&1
[[ $? -eq 1 ]] && pass "exits 1 when problems are found" || fail "exits 1 when problems are found"

d="$(make_repo exit-clean)"
printf '#!/usr/bin/env bash\necho hi\n' > "$d/tool.sh"
printf 'Run it with `bash tool.sh`\n' > "$d/README.md"
commit "$d"
NO_COLOR=1 bash "$CHECKER" "$d" >/dev/null 2>&1
[[ $? -eq 0 ]] && pass "exits 0 when clean" || fail "exits 0 when clean"
echo

# --- 6. --fix ------------------------------------------------------------
echo "6. --fix"
d="$(make_repo fixable)"
printf '#!/usr/bin/env bash\necho hi\n' > "$d/install.sh"
printf 'Run `./install.sh`\n' > "$d/README.md"
commit "$d"
git -C "$d" update-index --chmod=-x install.sh 2>/dev/null
NO_COLOR=1 bash "$CHECKER" --fix "$d" >/dev/null 2>&1
mode="$(git -C "$d" ls-files -s install.sh | awk '{print $1}')"
[[ "$mode" == "100755" ]] && pass "--fix stages the executable bit" ||
  fail "--fix stages the executable bit (mode is $mode)"

NO_COLOR=1 bash "$CHECKER" "$d" >/dev/null 2>&1
[[ $? -eq 0 ]] && pass "repo is clean after --fix" || fail "repo is clean after --fix"

echo
echo "─────────────────────────────────────────"
printf 'passed: %d   failed: %d\n' "$PASS" "$FAIL"
[[ "$FAIL" -eq 0 ]] || exit 1
echo "self-test green"
