# repo-hygiene

Catches the file-level defects that only surface at run time, on someone else's
machine.

```bash
./check-repo-hygiene.sh                 # this repository
./check-repo-hygiene.sh --all ..        # every repo in the workspace
./check-repo-hygiene.sh --fix .         # stage the safe fixes
./self-test.sh                          # prove the checker works (15 assertions)
```

Exit codes: **0** clean · **1** problems found · **2** usage/environment error.

---

## The bug this exists for

A shell script committed as mode `100644` works perfectly for the person who
wrote it. Their working copy has the executable bit; on Windows,
`core.fileMode=false` hides the difference completely. It fails for everyone
else, at run time:

```
/home/runner/work/_temp/xxxx.sh: line 1: ./install.sh: Permission denied
Error: Process completed with exit code 126.
```

Nothing in that message says the file **mode** is the problem.

This is not hypothetical. It broke `pssid-wpa-credential-manager` CI - all four
shell scripts were `100644`, so `./install.sh -y` died and took the entire
end-to-end smoke job with it - and it sat latent in `pssid-gui2`, where
`sudo scripts/provision-probes.sh`, the documented command for delivering config
to every probe, was also `100644`.

Running this checker across the workspace found a third instance nobody had
reported.

---

## Findings across the pSSID workspace

Run on all 10 repositories:

```
== ansible-playbook-pssid-daemon ==
  ERROR  defaults.sh is 100644 but is invoked directly somewhere in this repo
         seen at: README.md:64:./defaults.sh /var/lib/pssid/ansible-inventory-pssid-probes-example/
         seen at: defaults.sh:15:# sudo ./defaults.sh /var/lib/pssid/...
         fix: git -C ./ansible-playbook-pssid-daemon update-index --chmod=+x defaults.sh
  warn   no .gitattributes; nothing prevents CRLF from being committed

repositories: 10   errors: 1   warnings: 2
```

The `defaults.sh` finding is worth reading closely. Its README says:

```bash
chmod +x defaults.sh
./defaults.sh /var/lib/pssid/ansible-inventory-pssid-probes-example/
```

The `chmod +x` line **is the workaround**. Someone hit the bug, worked around it
by hand, and documented the workaround instead of fixing the mode - so every
operator since has had to do it too. Committing the bit removes that step.

---

## What it checks

| # | Check | Level |
|---|---|---|
| 1 | Scripts invoked directly are executable in git | error |
| 2 | No CRLF line endings in tracked shell scripts | error |
| 3 | `.gitattributes` pins `*.sh text eol=lf` | warn |
| 4 | Every shell script has a shebang | warn |
| 5 | Every shell script parses (`bash -n`) | error |
| 6 | `shellcheck -S error`, when installed | warn |

Check 2 matters because Git Bash runs a CRLF script fine while Linux does not:
the shebang becomes `/usr/bin/env bash\r`, which does not exist, and the error
names a program nobody typed. This repository hit exactly that and fixed it with
a `.gitattributes`; check 3 is what stops it coming back.

---

## How check 1 decides

Not every script should be executable. A library meant to be `source`d
(`scripts/lib/preflight.sh`) and a suite always invoked as `bash scripts/foo.sh`
are **correct** at `100644`. Demanding `+x` everywhere produces noise, and noisy
checkers get switched off.

So the rule is: **a script must be executable if something in the repository
invokes it directly.** Detection is positive-evidence-only - it looks for a real
`./script` or `sudo script` and reports where it saw it. The tempting inverse
("flag anything not preceded by an interpreter") was the first implementation and
it produced four false positives on `pssid-gui2` alone, including on a markdown
link, because `[x](../scripts/x.sh)` contains `./scripts/x.sh` as a substring.

A missed script is recoverable. An ignored checker is not.

Calibrated against the real repositories:

| Script | Referenced as | Verdict |
|---|---|---|
| `pssid-gui2` `scripts/lib/preflight.sh` | `source`d, plus prose | not flagged |
| `pssid-gui2` `scripts/seed-defaults.sh` | `bash scripts/seed-defaults.sh` | not flagged |
| `pssid-gui2` `docs/…(../scripts/tool.sh)` | markdown link | not flagged |
| `ansible-playbook-pssid-daemon/defaults.sh` | `./defaults.sh` | **flagged** |

---

## The self-test

`./self-test.sh` builds throwaway repositories with known-good and known-bad
content and asserts the verdict on each - 15 assertions covering detection,
**non**-detection, exit codes, and `--fix`. A linter whose false-positive rate
has not been measured is not worth running, and the non-detection cases are half
the suite for that reason.

```
passed: 15   failed: 0
self-test green
```

---

## `--fix`

Stages the executable bit via `git update-index --chmod=+x`. It **stages, never
commits** - review with `git diff --cached` first.

`git update-index` is the right tool rather than `chmod`: on a checkout with
`core.fileMode=false`, `chmod` changes the working file and git ignores it, so
the commit does not carry the fix. `update-index` writes the mode into the index
directly and works identically on every platform.

The other findings are deliberately **not** auto-fixed. Normalising line endings
rewrites every affected blob and wants a dedicated commit
(`git add --renormalize .`), and a missing shebang needs a human to decide which
interpreter.

---

## CI

`workflow.yml` is a drop-in GitHub Actions job:

```yaml
- uses: actions/checkout@v4
- run: bash projects/repo-hygiene/check-repo-hygiene.sh .
```

It needs no dependencies beyond `git` and `bash`, and runs in about a second.
`shellcheck` is used when present and skipped when not, so it never fails a
runner for a missing optional tool.

---

## Adopting this upstream

Written to be lifted into its own repository, or vendored per repo. The checker
is a single self-contained file with no configuration; the self-test is a second.
Copy both, or add this repo as a submodule and call it from CI.

There is a case for it living in `UMNET-perfSONAR/` as a shared workflow, since
the failure it catches has now occurred in three of the ten repositories.
