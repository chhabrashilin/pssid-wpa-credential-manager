# Data pipeline - investigation

**This project is deliberately not code.**

The other four projects in `projects/` ship working, tested software. This one
does not, and the reason is the point: the measurement pipeline cannot be built
responsibly from what is available in this workspace, and writing plausible-
looking Ansible for a schema nobody can see would be worse than writing nothing.

What follows is what the evidence actually shows, three defects found along the
way, and a specification for whoever has access to the missing pieces.

---

## The gap

Measurements are the **product** of the entire pSSID system. Everything else -
the GUI, the credential manager, the daemon, the probes - exists to produce
them. And the component that receives them is the least defined thing here:

| Repository | State |
|---|---|
| `ansible-role-pssid-datapipeline` | **Empty stub.** A `LICENSE` and a two-line `README.md` reading *"data analytics stack for pSSID"*. No tasks, no defaults, no templates. |
| `ansible-playbook-elastic` | **Not present in this workspace.** Referenced by `ansible-inventory-pssid-ilab/README.md`, which says *"follow instructions at ansible-playbook-elastic"*. |

So the documented path to standing up analytics points at a repository nobody
here can read, and the role that would automate it is a placeholder.

---

## What the evidence does show

Two archiving routes exist, and they are not documented together anywhere.

### Route A - syslog (the shipped default)

`pssid-daemon/pssid_config.json`:

```json
"archivers": [
  { "name": "syslog", "archiver": "syslog",
    "data": { "identity": "pssid", "facility": "1" } }
]
```

The daemon passes a syslog archive spec to the pScheduler batch processor for
every test (`batch_processor_format_template.j2`), with the facility taken from
`--facility` (default `local0`). Results land in the probe's syslog.
`ansible-playbook-pssid-daemon` then installs `ansible-role-filebeat`, so the
intended shape is:

```
test → pscheduler batch processor → syslog(local0) → filebeat → Elastic
```

### Route B - AMQP direct to Elastic (the iLab deployment)

`ansible-inventory-pssid-ilab/playbooks/files/pssid_conf.json` and
`files/rpi_meta.py` both carry:

```
amqp://elastic:elastic@pssid-elk.miserver.it.umich.edu
```

So the real UMich deployment appears to publish over AMQP to a RabbitMQ/Elastic
endpoint rather than going through syslog.

**Which route is current is not determinable from this workspace**, and that
question has to be answered before any of the specification below is worth
implementing.

---

## Three defects found while investigating

### 1. Credentials committed in plain text · **High**

`amqp://elastic:elastic@pssid-elk.miserver.it.umich.edu` appears in two tracked
files in `ansible-inventory-pssid-ilab`:

- `playbooks/files/pssid_conf.json:16`
- `playbooks/files/rpi_meta.py:11`

Username and password are both `elastic`, in git history, in a repository that
is public on GitHub. This is worth acting on independently of anything else in
this document - rotating the credential and moving it to a vaulted variable is a
contained change, and the git history will still need attention afterwards.

It is also the same class of problem the credential manager was built to solve
for wireless secrets. The pattern recurs because there is nowhere else obvious
to put a secret.

### 2. `validate_archivers.py` validates nothing · **Medium**

`ansible-inventory-pssid-ilab/playbooks/files/validate_archivers.py` is a
well-built validator - it knows the required and optional keys for
`bitbucket`, `failer`, `http`, `kafka`, `rabbitmq` and `syslog` archivers - and
it never runs, because of a one-word schema mismatch:

```python
if 'archives' not in config:
    exit(0)
archivers = config['archives']
```

The daemon's config uses the key **`archivers`**, not `archives`. Verified:

```console
$ python3 validate_archivers.py pssid-daemon/pssid_config.json
$ echo $?
0
```

Exit 0, no output, nothing checked. Anyone relying on this as a guard has no
guard.

**Fix:** accept `archivers` (and keep `archives` for compatibility if some other
producer emits it). Then wire it into the GUI's config generation, where it
would actually catch a malformed archiver before it reaches a probe.

### 3. The archiver schema is unvalidated end to end · **Medium**

`pssid-gui2`'s `assertDaemonValid` checks hosts, host groups, batches, jobs,
tests and schedules - but not `archivers`. And `validate_archivers.py`, which
knows the archiver rules, is not reachable from the GUI and does not run (see
above).

So a malformed archiver spec passes every check in the system and fails on the
probe, at measurement time, where the only symptom is missing data.

---

## Specification

For whoever has access to `ansible-playbook-elastic` and the production Elastic
cluster.

### Questions to answer first

1. **Which route is live** - syslog+filebeat, or AMQP direct? Both are
   configured somewhere; only one can be the intended path.
2. **What is the index schema?** The batch processor writes a pScheduler result
   plus the `reference` block the daemon builds (`SSID`, `batch_name`,
   `interface`, `timestamp`, plus any SSID-profile `data`). Whether Elastic has
   an explicit mapping for these or infers them decides whether a field can
   change safely.
3. **What is the retention policy?** At a two-minute schedule, one probe
   produces on the order of 700 batch runs a day.
4. **Is there a dashboard definition under version control**, or does the
   Grafana/Kibana state live only in the running instance? (`pSSID-docs` has a
   stub page `analytics-grafana.md` and another `analytics-installation.md`,
   both unwritten.)

### What `ansible-role-pssid-datapipeline` should contain

```
defaults/main.yml    endpoint, index/exchange names, retention, auth VARIABLES
                     (never literals -- see defect 1)
tasks/main.yml       install + configure the collector on the probe side
templates/           filebeat.yml.j2 or the AMQP archiver spec
meta/main.yml        dependencies
README.md            which route it implements, and the variables it needs
```

### A correctness issue that will affect the schema

`pssid-daemon-tests` (a sibling project here) found and reproduced a defect that
directly corrupts this pipeline's data:

> **D2 - the `reference` SSID is always the first globally defined profile.**
>
> The daemon builds the pScheduler `reference` block from
> `data["ssid_profiles"][0]` while executing `batch["ssid_profiles"]`. With more
> than one SSID profile, **every archived measurement is labelled with the wrong
> SSID.**
>
> ```
> batch declares ssid_profiles: ['SECOND']
> reference SSID actually sent: 'FIRST'
> ```

Any deployment with a single SSID profile is unaffected - which may be why it
has not surfaced. But a pipeline built on the assumption that
`reference.SSID` identifies the network measured will silently mis-attribute
results the moment a second profile is added.

**Fix D2 before building dashboards on that field.** See
`../pssid-daemon-tests/README.md`.

---

## Recommended order

1. **Rotate the AMQP credential and vault it.** Contained, unblocked by anything
   here, and the highest-severity finding.
2. **Fix `validate_archivers.py`'s key mismatch** and call it from the GUI's
   config generation. Small, and it closes a validation gap that currently fails
   silently on the probe.
3. **Fix daemon defect D2** so `reference.SSID` is trustworthy.
4. **Answer the four questions**, then write the role.
5. **Write `analytics-installation.md` and `analytics-grafana.md`** in
   `pSSID-docs` - both are currently "Content coming soon", and this is the
   least-documented part of the system.

Steps 1-3 are worth doing whatever the answer to step 4 turns out to be.
