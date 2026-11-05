# pSSID ecosystem projects

Supporting projects for the pSSID system, developed alongside the credential
manager because that is where the work was scoped - but **none of them depend on
the credential manager**, and each is designed to be lifted into its own
repository under `UMNET-perfSONAR/` when it is ready to be adopted.

Each project has its own `README.md` stating what it does, what it is verified
against, and what it deliberately does not claim.

| Project | What it solves | Status |
|---|---|---|
| [`repo-hygiene/`](repo-hygiene/) | The `100644` executable-bit class of bug that broke credential-manager CI and sat latent in `pssid-gui2` | **Working** - 15-assertion self-test, run against all 10 local repos, found a third instance |
| [`pssid-daemon-tests/`](pssid-daemon-tests/) | `pssid-daemon.py` is 738 lines, runs as root on every probe, and had zero tests | **Working** - 66 tests, 5 confirmed defects pinned |
| [`pssid-probe-health/`](pssid-probe-health/) | Nothing in the system knows whether a probe is actually testing | **Working** - CLI + systemd timer, 63 tests, 7-scenario demo |
| [`docs-content/`](docs-content/) | 22 of 34 `pSSID-docs` pages are literal "not been written yet" stubs | **4 pages written from source**, drop-in |
| [`datapipeline-investigation/`](datapipeline-investigation/) | `ansible-role-pssid-datapipeline` is an empty stub; `ansible-playbook-elastic` is referenced but absent | **Investigation + spec** - deliberately not code; 3 defects found |

---

## Why these five

They came out of reading the whole ecosystem, and they are ordered by how much
of the system is blind without them.

The pSSID system has a good generation story and a poor **observation** story.
The GUI generates a config and validates it thoroughly. The credential manager
renders and delivers `wpa_supplicant` files. Both are careful. But once a file
reaches a probe, *nothing anywhere can tell you whether the probe is working*:

- [`pssid-daemon.py:483-486`](../../../pssid-daemon/pssid-daemon.py) - a missing
  `wpa_supplicant` conf makes the batch `return`. Silent. No test runs.
- `pssid-gui2/scripts/provision-probes.sh` - states in its own header that it can
  only report *delivery*, never adoption.
- The daemon writes to syslog and nothing aggregates it.

So a probe with a broken config is indistinguishable from a healthy one. That is
what `pssid-probe-health` exists to fix, and what `pssid-daemon-tests` exists to
stop regressing.

`repo-hygiene` is in the list because the bug that started this work - a shell
script committed without its executable bit - was invisible until it broke CI,
existed in two repositories simultaneously, and will recur.

`docs-content` and `datapipeline-investigation` address the two places where the
project's own documentation admits it is incomplete.

---

## Running everything

```bash
bash projects/run-all.sh
```

Runs every project's own suite and reports one summary. Requires `bash` and
`python3` (3.9+); no third-party packages, deliberately - see each project's
README for why.
