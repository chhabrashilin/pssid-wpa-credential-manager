# docs-content

Drop-in pages for [`pSSID-docs`](../../../../pSSID-docs), written from the
source they document.

## The gap

`pSSID-docs` has 34 pages. **22 of them are stubs** whose entire content is:

```markdown
# wpa_supplicant

This page has not been written yet.

```txt
Content coming soon.
```
```

Including `config-wpa-supplicant.md` - the page an operator looks for first when
a probe stops testing, and the subject of the credential manager this repository
holds.

## What is here

Four pages, each written by reading the code it describes rather than by
paraphrasing existing prose.

| Page | Sourced from |
|---|---|
| `config-wpa-supplicant.md` | `pssid-daemon.py` (the file contract, the silent skip), the credential manager's derivation and delivery, `ansible-playbook-pssid-daemon`'s vault workflow |
| `config-pssid-json.md` | the shipped `pssid_config.json`, the daemon's `process_gui_conf` / `variable_substitution` / `schedule_batch`, and `pssid-gui2`'s `assertDaemonValid` |
| `daemon-useful-flags.md` | the daemon's `argparse` block and what each flag actually does |
| `logs-daemon.md` | every `syslog.syslog(...)` call in the daemon, and what each message means |

To adopt: copy into `pSSID-docs/docs/`, replacing the stub of the same name.
`pSSID-docs` renders markdown directly (`main.js` + `marked.min.js`), so no
build step or front-matter is needed.

## Why only four

The other 18 stubs cover Grafana, Elastic installation, PXE boot, WiFi-6
hardware, Docker troubleshooting and the GUI's Ansible deployment. Writing those
would mean inventing specifics - exact package versions, dashboard layouts,
hardware revisions - that cannot be checked against anything in this workspace.

A confidently-worded page that is subtly wrong is worse than a stub, because a
stub tells the reader to go and ask someone. These four are written only where
the source could be read and quoted.

`analytics-grafana.md` and `analytics-installation.md` are the two most valuable
of the remaining stubs; see [`../datapipeline-investigation`](../datapipeline-investigation)
for what would need answering first.

## Things these pages document that were not written down anywhere

Found while reading the source, and worth flagging because operators currently
have no way to know them:

- **A missing `wpa_supplicant_<profile>.conf` silently skips the batch.** The
  daemon logs one `LOG_ERR` and then behaves normally forever.
- **`parallel` and `continue-if` must be JSON strings**, and only the exact
  capitalisation `"True"` / `"False"` converts. `"true"` reaches pScheduler as a
  string.
- **`hosts_regex` uses `re.match`** - a prefix match, not a full match.
- **Variable substitution replaces the whole value rather than interpolating**,
  so `"$interface-monitor"` resolves to `"wlan0"`, silently losing the suffix.
- **Host metadata beats group metadata** (first-write-wins, host applied first).
- **The daemon reads its Jinja template relative to the working directory**, so
  a manual run from the wrong directory fails at the first batch.
- **`--debug` has no effect and debug output is always on.**

The last two are defects rather than design; both are pinned with reproductions
in [`../pssid-daemon-tests`](../pssid-daemon-tests). The pages describe the
current behaviour so an operator is not misled in the meantime.
