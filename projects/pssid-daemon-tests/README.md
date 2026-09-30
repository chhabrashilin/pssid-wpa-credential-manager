# pssid-daemon test harness

A dependency-free test suite for `pssid-daemon.py` — 738 lines of Python that
run as **root on every probe** and, before this, had **no tests at all**.

```bash
./run-tests.sh
```

```
Daemon under test: /path/to/pssid-daemon/pssid-daemon.py
......................................................................
Ran 81 tests in 0.59s

OK
```

---

## Why the daemon had no tests

Not neglect — it was genuinely un-importable. Lines 22-24:

```python
from croniter import croniter
from jinja2 import Template
import pscheduler.batchprocessor
```

`croniter` is a third-party package and `pscheduler` ships only as part of a
perfSONAR install, so `import pssid_daemon` fails on any machine that is not a
provisioned probe. On top of that the filename contains a hyphen, so it is not a
valid module name in the first place.

`harness/` solves both:

| File | Job |
|---|---|
| `harness/stubs.py` | Minimal stand-ins for `croniter`, `pscheduler.batchprocessor` and `syslog`, installed into `sys.modules` before import. Captures every syslog line and every batch submitted. |
| `harness/loader.py` | Loads `pssid-daemon.py` by path via `importlib`, once, cached. |
| `harness/fixtures.py` | Config builders shaped exactly like the real `pssid_config.json`. |
| `harness/__init__.py` | `DaemonTestCase`: per-test state reset, a `subprocess.run` capture helper, and `assertSyslogContains`. |

`jinja2` is deliberately **not** stubbed — it is an ordinary pip package and the
template rendering is real logic worth exercising against the real engine.

### Requirements

`python3` (3.9+) and `jinja2`. That is the entire list, on purpose: this suite
has to be runnable on a CI runner, a developer laptop, and a probe, without a
perfSONAR installation.

---

## What is covered

| Suite | Tests | Subject |
|---|---|---|
| `test_config_contract.py` | 17 | The rules `pssid_config.json` must satisfy — the daemon-side truth behind the GUI's `assertDaemonValid` |
| `test_layer_contract.py` | 14 | The `wpa_supplicant` file contract, namespace setup, and argv-only helper calls |
| `test_layer_methods.py` | 15 | Which layer 2 / layer 3 helper runs for an SSID profile's `layer2_script` / `layer3_script`, and what is refused |
| `test_variable_substitution.py` | 14 | `$placeholder` resolution, including four genuinely surprising rules |
| `test_scheduling.py` | 11 | Earliest-schedule-wins selection and the re-scheduling loop |
| `test_defects.py` | 10 | Five confirmed defects, pinned |

### The GUI contract

`pssid-gui2` generates the config the daemon consumes and validates it in
`assertDaemonValid`. That validator was written by reading the daemon, and
nothing keeps the two in sync. `test_config_contract.py` asserts each rule
against the daemon's **actual behaviour**, so a daemon change breaks this suite
and the GUI's validator is known to need updating. Examples it pins:

- `job.parallel` must be the exact string `"True"` / `"False"` — `"true"` stays a
  string and reaches pscheduler as one.
- `continue-if` must be a string; a real boolean raises `AttributeError` at
  daemon line 223.
- Host metadata beats group metadata (first-write-wins in `add_metadata`).
- Group `hosts_regex` uses `re.match`, so patterns are **prefix** matches.

### The credential-manager contract

`test_layer_contract.py` is the executable version of `docs/integration.md`. It
asserts the daemon opens exactly
`/etc/wpa_supplicant/wpa_supplicant_<profile>.conf` — the path
`scripts/pssid-credmgr-pull.sh` writes — and that it never restarts the
`wpa_supplicant` service. If the daemon ever changes that filename, this suite
fails and the pull tooling is known to be wrong.

It also pins the silent-skip: with the conf file absent, `process_on_layer_2`
returns having executed **nothing**, with only a syslog line to show for it.

---

## Defects found

All five were confirmed by execution, not by reading. Severity is blast radius
on a real deployment.

### D1 — Tests accumulate across jobs · **High**

`job_tests = []` is initialised at line 171, **outside** the `for job_name in
batch["jobs"]` loop at line 212, and never cleared. Job *N* is rendered with the
tests of jobs 1..*N*, and `iteration` (line 244) is wrong the same way.

Observed with two jobs of one test each:

```
job job_one: iterations=1 tests=['www.google.com']
job job_two: iterations=2 tests=['www.google.com', 'www.ebay.com']
```

Every job after the first re-runs all preceding tests. Single-job batches —
including the shipped config — are unaffected, which is why it has survived.

**Fix:** move `job_tests = []` inside the job loop.

### D2 — Archived results carry the wrong SSID · **High**

Lines 187-189 build the pscheduler `reference` block from
`data["ssid_profiles"][0]` — the first *globally defined* profile — while
`execute_batch` (line 631) iterates `batch["ssid_profiles"]`.

```
batch declares ssid_profiles: ['SECOND']
reference SSID actually sent: 'FIRST'
```

With more than one profile, the data pipeline cannot attribute a measurement to
the network it was taken on.

**Fix:** derive the reference SSID from the profile being executed. Needs a
signature change — the transform runs once per batch (line 330) but the SSID
varies per profile inside `execute_batch`.

### D3 — `sys.exit` without parentheses · **Medium**

Line 319 evaluates the function object and discards it. "No batch found" logs an
error and carries on, scheduling nothing. The probe stays up looking healthy and
does no work — the same silent-idle failure as the missing conf file.

**Fix:** `sys.exit(1)`.

### D4 — `--debug` is a no-op · **Low**

Line 687 (`debug = True`) binds a local inside `main` that nothing reads. Line
654 (`if debug:`) resolves to the module-level `debug` *function* from line 637,
which is always truthy. Debug output is permanently on and the flag does nothing.

**Fix:** pass the flag explicitly into `run_batch_processor`.

### D5 — Template path is relative to CWD · **Medium**

Line 167 opens `batch_processor_format_template.j2` with no anchor, so the daemon
only works when CWD happens to contain it. Run from anywhere else it raises
`FileNotFoundError` at the first batch — long after startup looked fine.

**Fix:** resolve against `os.path.dirname(os.path.abspath(__file__))`.

### Shell use

The layer 2 / layer 3 helper calls pass an argument list with no shell, so a
hostile `ssid_profile` or `test_interface` stays a single argument
(`TestShellInjectionSurface`). The remaining namespace and `resolv.conf`
commands still use `shell=True` with the interface interpolated. Those values
come from the GUI-generated, SSH-delivered config, so this is **not remotely
reachable**, but the GUI's validation is still the only guard for them.

**Fix:** convert those calls to argument lists as well.

---

## On characterisation tests

`test_defects.py` **asserts the wrong behaviour on purpose**. Each test fails the
day the bug is fixed, and that failure is the signal to delete it and assert the
correct behaviour instead. Every such assertion carries a message saying so:

```python
self.assertEqual(
    urls(jobs[1]),
    ["www.google.com", "www.ebay.com"],
    "D1 appears to be FIXED -- job_two no longer inherits job_one's tests. "
    "Delete this test and assert the correct behaviour instead.",
)
```

This is the standard move for putting a safety net under untested code before
changing it: write down what it *does*, then change it deliberately.

---

## Layout

```
harness/
  stubs.py       croniter / pscheduler / syslog stand-ins + capture
  loader.py      importlib loading of a hyphenated filename
  fixtures.py    config builders matching the real schema
  __init__.py    DaemonTestCase base
tests/
  test_config_contract.py
  test_layer_contract.py
  test_layer_methods.py
  test_variable_substitution.py
  test_scheduling.py
  test_defects.py
run-tests.sh
```

## Adopting this upstream

Written to be lifted into `UMNET-perfSONAR/pssid-daemon` as its `tests/`
directory. The only coupling to this repository is the default relative path in
`harness/loader.py`; set `PSSID_DAEMON_PATH` or edit `_DEFAULT_RELATIVE` and it
runs anywhere.

A reasonable adoption order:

1. Merge the harness and suites as-is — they pass against `main` today.
2. Fix **D1** and **D2** (the two High findings), deleting the characterisation
   tests as each goes green.
3. Add the suite to CI. There is no CI on `pssid-daemon` at all right now.
