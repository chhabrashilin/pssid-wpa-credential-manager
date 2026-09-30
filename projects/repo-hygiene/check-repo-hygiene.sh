#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# check-repo-hygiene — catch the file-level defects that only surface at run
# time, on someone else's machine.
#
#   ./check-repo-hygiene.sh [REPO ...]     # default: the current repository
#   ./check-repo-hygiene.sh --all ..       # every git repo under a directory
#   ./check-repo-hygiene.sh --fix .        # apply the safe fixes
#
# Exit codes:  0 clean · 1 problems found · 2 usage/environment error
#
# ---------------------------------------------------------------------------
# WHY THIS EXISTS
#
# A shell script committed as mode 100644 works perfectly for the person who
# wrote it -- their working copy has the executable bit, and on Windows
# core.fileMode=false hides the difference entirely. It fails for everyone else,
# at run time, with "Permission denied" and exit 126, and nothing in the message
# says the file MODE is the problem.
#
# That is not hypothetical. It broke pssid-wpa-credential-manager CI (all four
# scripts were 100644, so `./install.sh -y` died and took the whole end-to-end
# job with it) and it sat latent in pssid-gui2, where
# `sudo scripts/provision-probes.sh` -- the documented command for delivering
# config to every probe -- was also 100644.
#
# The same class covers CRLF endings (Git Bash tolerates them; a Linux probe
# fails at the shebang) and a missing .gitattributes to prevent them.
# ---------------------------------------------------------------------------
set -uo pipefail

# --- Output ----------------------------------------------------------------
if [[ -t 1 ]] && [[ -z "${NO_COLOR:-}" ]]; then
  C_RED=$'\033[31m'; C_YEL=$'\033[33m'; C_GRN=$'\033[32m'
  C_DIM=$'\033[2m'; C_BLD=$'\033[1m'; C_OFF=$'\033[0m'
else
  C_RED=''; C_YEL=''; C_GRN=''; C_DIM=''; C_BLD=''; C_OFF=''
fi

ERRORS=0
WARNINGS=0
CHECKED=0
FIX=false
FIXES_APPLIED=0

err()  { printf '%s  ERROR%s  %s\n' "$C_RED" "$C_OFF" "$1"; ERRORS=$((ERRORS + 1)); }
warn() { printf '%s  warn %s  %s\n' "$C_YEL" "$C_OFF" "$1"; WARNINGS=$((WARNINGS + 1)); }
ok()   { [[ -n "${VERBOSE:-}" ]] && printf '%s  ok   %s  %s\n' "$C_GRN" "$C_OFF" "$1"; return 0; }
note() { printf '         %s%s%s\n' "$C_DIM" "$1" "$C_OFF"; }

usage() {
  sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-2}"
}

# --- Arguments -------------------------------------------------------------
REPOS=()
SCAN_ALL=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --fix)   FIX=true ;;
    --all)   SCAN_ALL=true ;;
    -v|--verbose) VERBOSE=1 ;;
    -h|--help) usage 0 ;;
    -*)      echo "Unknown option: $1" >&2; usage 2 ;;
    *)       REPOS+=("$1") ;;
  esac
  shift
done

command -v git >/dev/null || { echo "ERROR: git is required" >&2; exit 2; }

if $SCAN_ALL; then
  root="${REPOS[0]:-.}"
  REPOS=()
  skipped=0
  while IFS= read -r d; do
    candidate="$(dirname "$d")"
    # A stray or partial .git directory is not a finding when we went looking
    # for repositories ourselves -- only when the user named the path.
    if git -C "$candidate" rev-parse --git-dir >/dev/null 2>&1; then
      REPOS+=("$candidate")
    else
      skipped=$((skipped + 1))
    fi
  done < <(find "$root" -maxdepth 2 -name .git -type d 2>/dev/null | sort)
  [[ ${#REPOS[@]} -eq 0 ]] && { echo "No git repositories found under $root" >&2; exit 2; }
  [[ $skipped -gt 0 ]] &&
    printf '%s(skipped %d path(s) with an unusable .git)%s\n' "$C_DIM" "$skipped" "$C_OFF"
elif [[ ${#REPOS[@]} -eq 0 ]]; then
  REPOS=(".")
fi

# ---------------------------------------------------------------------------
# Which scripts MUST be executable?
#
# Not all of them. A library meant to be `source`d (scripts/lib/preflight.sh)
# and a suite always invoked as `bash scripts/foo.sh` are correct at 100644;
# demanding +x everywhere would be noise, and noisy checks get switched off.
#
# The real rule is: a script is REQUIRED to be executable if something in the
# repository invokes it WITHOUT an interpreter prefix. So we search the tracked
# files -- docs, CI workflows, Makefiles, other scripts, and each script's own
# usage header -- for `./script`, `sudo script`, or a bare `scripts/foo.sh` at a
# command position, and ignore any occurrence preceded by bash/sh/source/.
# ---------------------------------------------------------------------------
#
# Detection is POSITIVE-EVIDENCE-ONLY: we flag a script only when we can point
# at a real direct invocation -- `./x.sh` or `sudo x.sh`. The tempting inverse
# ("flag anything not preceded by an interpreter") produces false positives on
# every prose mention and every markdown link, and a checker that cries wolf
# gets disabled. A missed script is recoverable; an ignored checker is not.
#
# Calibrated against the real repositories:
#   pssid-gui2 scripts/lib/preflight.sh   sourced + prose only  -> not flagged
#   pssid-gui2 scripts/seed-defaults.sh   `bash scripts/...`    -> not flagged
#   ansible-playbook-pssid-daemon/defaults.sh  `./defaults.sh`  -> FLAGGED
#
requires_exec_bit() { # requires_exec_bit <repo> <script-path>
  local repo="$1" script="$2" base
  base="$(basename "$script")"

  local esc_path esc_base
  esc_path="$(printf '%s' "$script" | sed 's/[.[\*^$()+?{}|]/\\&/g')"
  esc_base="$(printf '%s' "$base" | sed 's/[.[\*^$()+?{}|]/\\&/g')"

  # `./script` -- but NOT the `./` inside a relative markdown link such as
  # `[x](../scripts/x.sh)`, so the character before `./` must not be a dot,
  # a slash, or part of a word.
  local dot_slash="(^|[^./[:alnum:]_-])\./(${esc_path}|${esc_base})([[:space:]]|\$|\`|\"|')"

  # `sudo script`, `sudo -E script`, `sudo ./script`
  local sudo_form="(^|[^[:alnum:]_-])sudo[[:space:]]+(-[A-Za-z-]+[[:space:]]+)*(\./)?(${esc_path}|${esc_base})([[:space:]]|\$|\`|\"|')"

  local files=('*.md' '*.yml' '*.yaml' '*.sh' 'Makefile' '*/Makefile')

  git -C "$repo" grep -IqE -- "$dot_slash" -- "${files[@]}" 2>/dev/null && return 0
  git -C "$repo" grep -IqE -- "$sudo_form" -- "${files[@]}" 2>/dev/null && return 0
  return 1
}

# Print where the direct invocation was seen, so an error is actionable.
show_invocation() { # show_invocation <repo> <script-path>
  local repo="$1" script="$2" base esc_path esc_base
  base="$(basename "$script")"
  esc_path="$(printf '%s' "$script" | sed 's/[.[\*^$()+?{}|]/\\&/g')"
  esc_base="$(printf '%s' "$base" | sed 's/[.[\*^$()+?{}|]/\\&/g')"
  local both="((^|[^./[:alnum:]_-])\./|(^|[^[:alnum:]_-])sudo[[:space:]]+(-[A-Za-z-]+[[:space:]]+)*(\./)?)(${esc_path}|${esc_base})([[:space:]]|\$|\`|\"|')"
  git -C "$repo" grep -InE -- "$both" -- '*.md' '*.yml' '*.yaml' '*.sh' 'Makefile' 2>/dev/null |
    head -2 | while IFS= read -r line; do note "seen at: ${line:0:100}"; done
}

check_repo() { # check_repo <path>
  local repo="$1" name
  name="$(basename "$(cd "$repo" && pwd)")"

  if ! git -C "$repo" rev-parse --git-dir >/dev/null 2>&1; then
    err "$name: not a git repository"
    return
  fi

  CHECKED=$((CHECKED + 1))
  printf '\n%s== %s ==%s\n' "$C_BLD" "$name" "$C_OFF"

  local found_any=false

  # --- 1. Executable bit -------------------------------------------------
  while IFS=$'\t' read -r mode path; do
    [[ -z "$path" ]] && continue
    found_any=true
    if [[ "$mode" == "100755" ]]; then
      ok "$path is executable"
      continue
    fi
    if requires_exec_bit "$repo" "$path"; then
      err "$path is $mode but is invoked directly somewhere in this repo"
      show_invocation "$repo" "$path"
      note "fix: git -C $repo update-index --chmod=+x $path"
      if $FIX; then
        git -C "$repo" update-index --chmod=+x "$path" 2>/dev/null &&
          { note "FIXED (staged)"; FIXES_APPLIED=$((FIXES_APPLIED + 1)); }
      fi
    else
      ok "$path is $mode (only ever invoked via an interpreter)"
    fi
  done < <(git -C "$repo" ls-files -s -- '*.sh' 2>/dev/null |
             awk '{print $1 "\t" substr($0, index($0,$4))}')

  $found_any || { note "no shell scripts tracked"; return; }

  # --- 2. CRLF line endings ---------------------------------------------
  # Git Bash runs a CRLF script fine. Linux does not: the shebang becomes
  # "/usr/bin/env bash\r", which does not exist, and the error names a program
  # nobody typed.
  local crlf=()
  while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    if git -C "$repo" show ":$path" 2>/dev/null | head -c 8000 | grep -qU $'\r'; then
      crlf+=("$path")
    fi
  done < <(git -C "$repo" ls-files -- '*.sh' 2>/dev/null)

  if [[ ${#crlf[@]} -gt 0 ]]; then
    err "${#crlf[@]} shell script(s) have CRLF endings in the index:"
    for p in "${crlf[@]}"; do note "$p"; done
    note "fix: add '*.sh text eol=lf' to .gitattributes, then: git add --renormalize ."
  else
    ok "no CRLF in tracked shell scripts"
  fi

  # --- 3. .gitattributes guard ------------------------------------------
  if git -C "$repo" ls-files --error-unmatch .gitattributes >/dev/null 2>&1; then
    if git -C "$repo" show :.gitattributes 2>/dev/null | grep -qE '\*\.sh.*eol=lf'; then
      ok ".gitattributes pins *.sh to LF"
    else
      warn ".gitattributes exists but does not pin '*.sh text eol=lf'"
      note "without it, a checkout on Windows can reintroduce CRLF"
    fi
  else
    warn "no .gitattributes; nothing prevents CRLF from being committed"
    note "fix: echo '*.sh text eol=lf' >> $repo/.gitattributes"
  fi

  # --- 4. Shebangs -------------------------------------------------------
  while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    local first
    first="$(git -C "$repo" show ":$path" 2>/dev/null | head -1 | tr -d '\r')"
    if [[ "$first" != \#!* ]]; then
      warn "$path has no shebang (first line: ${first:0:40})"
    fi
  done < <(git -C "$repo" ls-files -- '*.sh' 2>/dev/null)

  # --- 5. Syntax ---------------------------------------------------------
  # A syntax error in a rarely-run script (restore.sh, an upgrade path) is
  # found at the worst possible moment otherwise.
  local bad_syntax=()
  while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    [[ -f "$repo/$path" ]] || continue
    bash -n "$repo/$path" 2>/dev/null || bad_syntax+=("$path")
  done < <(git -C "$repo" ls-files -- '*.sh' 2>/dev/null)

  if [[ ${#bad_syntax[@]} -gt 0 ]]; then
    for p in "${bad_syntax[@]}"; do err "$p does not parse (bash -n)"; done
  else
    ok "all shell scripts parse"
  fi

  # --- 6. shellcheck, when present --------------------------------------
  if command -v shellcheck >/dev/null 2>&1; then
    local sc_issues=0
    while IFS= read -r path; do
      [[ -z "$path" ]] && continue
      [[ -f "$repo/$path" ]] || continue
      shellcheck -S error -f gcc "$repo/$path" 2>/dev/null | while IFS= read -r line; do
        printf '%s  shellcheck%s %s\n' "$C_YEL" "$C_OFF" "$line"
      done
      shellcheck -S error "$repo/$path" >/dev/null 2>&1 || sc_issues=$((sc_issues + 1))
    done < <(git -C "$repo" ls-files -- '*.sh' 2>/dev/null)
    [[ $sc_issues -eq 0 ]] && ok "shellcheck clean at severity=error"
  else
    note "shellcheck not installed; skipping static analysis"
  fi
}

# --- Run -------------------------------------------------------------------
printf '%srepo hygiene%s\n' "$C_BLD" "$C_OFF"
$FIX && printf '%smode: --fix (changes are STAGED, never committed)%s\n' "$C_DIM" "$C_OFF"

for r in "${REPOS[@]}"; do
  check_repo "$r"
done

printf '\n%s─────────────────────────────────────────%s\n' "$C_DIM" "$C_OFF"
printf 'repositories: %d   errors: %d   warnings: %d\n' "$CHECKED" "$ERRORS" "$WARNINGS"
$FIX && [[ $FIXES_APPLIED -gt 0 ]] &&
  printf '%sstaged %d fix(es) -- review with `git diff --cached` before committing%s\n' \
    "$C_GRN" "$FIXES_APPLIED" "$C_OFF"

[[ $ERRORS -eq 0 ]] || exit 1
printf '%sclean%s\n' "$C_GRN" "$C_OFF"
