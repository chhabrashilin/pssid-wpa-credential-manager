# pssid-probe-health

Answers one question that nothing else in the pSSID system can answer:

> **Is this probe actually testing?**

```bash
./pssid-probe-health              # human summary; exit 0 / 1 / 2
./pssid-probe-health --json       # machine readable
./run-tests.sh                    # 63 tests
./demo.sh                         # simulated probes on a real filesystem
```

---

## The blind spot

A pSSID probe can be powered on, reachable by SSH, running its daemon, holding a
valid config — and testing **nothing at all**, indefinitely, with no signal
anywhere.

The mechanism is four lines of `pssid-daemon.py` (483-486):

```python
wpa_supplicant_conf_file = f"/etc/wpa_supplicant/wpa_supplicant_{ssid_profile}.conf"
if not os.path.exists(wpa_supplicant_conf_file):
    syslog.syslog(syslog.LOG_ERR, f"Error: ... does not exist.")
    print(f"Error: ... does not exist.")
    return
```

A missing credential file makes the batch `return`. No exception, no retry, no
alert. The daemon carries on scheduling batches that do nothing.

Nothing catches it:

| Component | What it knows | What it cannot know |
|---|---|---|
| pssid-gui2 | that a batch references a defined SSID profile | whether the probe holds that profile's credentials |
| `provision-probes.sh` | that `pssid_config.json` was **delivered** | whether the daemon adopted it — [its own header says so](../../../pssid-gui2/scripts/provision-probes.sh) |
| credential manager | that a render was pulled | whether the probe can use it |
| the daemon | everything | it only writes to syslog, which nothing aggregates |

So this exists. It runs **on** the probe, where the answer actually lives.

---

## What it checks

| Check | CRITICAL when | Why it matters |
|---|---|---|
| `config.present` | missing or malformed | the daemon exits 1 (lines 33-36) |
| `config.age` | — (warns when stale) | provisioning may have silently stopped reaching this probe |
| `host.known` | hostname not in the config | the daemon exits 1 (lines 299-302) |
| **`wpa.configs`** | **any declared profile has no conf file** | **the silent skip** |
| `daemon.running` | no `pssid-daemon` process | invisible at the network level |
| `interfaces` | a declared test interface is absent | batches cannot run |
| `credmgr.sync` | — (advisory) | which profiles are credential-manager managed |

`wpa.configs` is the point of the project. It resolves which SSID profiles this
probe *should* hold by replaying the daemon's own host matching — the host's
batches, plus every host group matched by name or by `hosts_regex`, using
`re.match` exactly as the daemon does — and then checks that each has a
non-empty conf file.

### Sample: the failure nothing else sees

```
probe: probe-partial

  [ok] config.present: /etc/pssid/pssid_config.json present and parses
  [ok] config.age: config last changed 0d ago
  [ok] host.known: probe-partial runs 1 batch(es)
  [XX] wpa.configs: 1 of 2 SSID profile(s) have no wpa_supplicant config: MWireless
       -> Batches using these profiles are being SILENTLY SKIPPED. Deliver them:
          CREDMGR_TOKEN=... pssid-credmgr-pull.sh <base-url> MWireless
  [ok] daemon.running: pssid-daemon is running
  [ok] interfaces: test interface(s) present: wlan0

  CRITICAL -- this probe is NOT TESTING
```

Every other line is green. The probe looks healthy by any other measure.

---

## Three design rules

**1. Never claim more than was observed.** `provision-probes.sh` gets this right
— it reports that a file was *delivered*, never that a probe adopted it, because
delivery is all it can see. Every check here carries the evidence behind its
verdict.

**2. "Cannot tell" is not "healthy".** `UNKNOWN` outranks `OK` in the severity
ordering, so a check that could not run never contributes to a green verdict.
This was caught by a real test failure while writing the suite: an empty `/proc`
means *enumeration failed*, not *the daemon is absent*, and conflating them would
report a broken probe as fine.

**3. No secrets, ever.** A `wpa_supplicant` conf holds a network-equivalent
credential — a 64-hex PSK or an NT hash. The report describes these files
(existence, size, mode) and never quotes a byte. Six tests enforce this,
including on the failure path, which formats more strings and so gets its own
check.

---

## Exit codes

| Code | Meaning |
|---|---|
| 0 | healthy (or only `UNKNOWN` results) |
| 1 | warnings — still testing |
| 2 | critical — **not testing** |

Nagios/Icinga-compatible, and directly usable from cron or a systemd timer.

---

## Deployment

```bash
sudo systemd/install.sh
```

Installs the package to `/usr/local/lib`, a launcher at
`/usr/local/bin/pssid-probe-health`, and a timer that reports every 15 minutes
with a 2-minute random spread so a fleet does not stampede a collector.

The unit sets `SuccessExitStatus=0 1 2` deliberately: a probe reporting "not
testing" is a **successful run** with an unhealthy verdict. The verdict travels
in the report, not in the unit state — otherwise `systemctl --failed` fills with
units that did exactly their job.

To ship reports somewhere, set in `/etc/pssid/health.env`:

```sh
PSSID_HEALTH_ARGS=--post https://credmgr.example.edu/api/v1/probe-health
```

A collector that cannot be reached is reported to stderr and **never changes the
probe's verdict**: the probe's health is a fact about the probe, not about
whether a server was up.

---

## Testing

63 tests, standard library only.

| Suite | Tests | Approach |
|---|---|---|
| `tests/test_checks.py` | 44 | in-memory `FakeEnvironment` — logic |
| `tests/test_integration.py` | 19 | real fixture filesystems via `--root` — the tool |

Both layers earn their place. A fake that agreed with a buggy `exists()` would
let unit tests pass; the integration suite builds real directories, real
zero-byte files, real `chmod 0644`, and a real `/proc` tree, and drives the
actual CLI.

`--root` treats a directory as `/`, which is what makes the integration layer
possible without root or hardware. It applies to `/proc` too, so daemon liveness
is exercised like every other check rather than being the one thing that can only
be tested on a probe.

### `./demo.sh`

Seven scenarios on real filesystems: healthy, the silent skip, the zero-byte
placeholder (`ansible-playbook-pssid-daemon` ships one), an unknown hostname,
loose permissions, JSON output with a live no-leak check against real credential
content, and the exit codes.

---

## Requirements

`python3` 3.9+. Nothing else, deliberately — probes are Ansible-provisioned and
should not need a `pip install` to report their own health. HTTP posting uses
`urllib` from the standard library.

---

## Adopting this upstream

Written to be lifted into `UMNET-perfSONAR/pssid-probe-health`, or vendored into
`ansible-role-pssid-daemon` so every probe gets it at provision time. An
`ansible/` directory is included as the natural home for that role task.

A sensible order:

1. Deploy read-only, no collector. Run `pssid-probe-health` by hand on a few
   probes and see what the fleet actually looks like.
2. Enable the timer. `journalctl -u pssid-probe-health` becomes the per-probe
   record.
3. Add `--post` once something exists to receive it — the natural home is a
   `POST /api/v1/probe-health` endpoint on the credential manager, which already
   has the fleet view this data belongs in (see `PLAN.local.md`, W3).
