# Daemon flags

Command-line options for `pssid-daemon.py`.

```
pssid-daemon.py [--config PATH] [--hostname NAME] [--facility FACILITY]
                [--validate] [--debug]
```

## `--config PATH`

Path to the configuration file.

**Default:** `/etc/pssid/pssid_config.json`

Useful for testing a candidate config without replacing the live one:

```bash
sudo pssid-daemon.py --config /tmp/candidate.json --validate
```

## `--hostname NAME`

Override the hostname used to match a `hosts` entry.

**Default:** the system hostname, from `socket.gethostname()`.

The daemon exits 1 if no `hosts` entry matches. This flag lets you check what a
*different* probe would do, from anywhere:

```bash
# What would probe-7 run, according to this config?
pssid-daemon.py --config ./pssid_config.json --hostname probe-7 --validate
```

It is also the workaround when a probe's hostname does not match the GUI entry
— though correcting one or the other is the real fix.

## `--facility FACILITY`

Syslog facility for the archived measurement records written by the pScheduler
batch processor.

**Default:** `local0`

Accepts the suffix, not the full constant: `local0` … `local7`, `daemon`.
Internally this becomes `syslog.LOG_LOCAL0`, so an unrecognised value raises
`AttributeError` at startup rather than falling back.

This sets the facility for **test results**. The daemon's own operational
messages always use the facility opened at startup with ident `pssid`.

## `--validate`

Load and process the config, report problems, then exit **without scheduling
anything**.

```bash
sudo pssid-daemon.py --validate
```

This is the dry run. It performs the full path — loads the JSON, matches this
host, collects batches from the host and its groups, resolves metadata,
substitutes variables, looks up every job and test, and renders each batch for
the batch processor — then exits 0 with `The config file is validated.`

It catches:

- a hostname matching no `hosts` entry (exits 1)
- batches referencing an undefined job, test or schedule
- a batch with no SSID profiles
- `parallel` / `continue-if` sent as JSON booleans instead of strings
- `$variables` with no matching metadata

It does **not** check anything about the probe itself: whether the wireless
interface exists, whether `/etc/wpa_supplicant/wpa_supplicant_<profile>.conf` is
present, or whether the credentials work. A config can validate cleanly on a
probe that will never successfully run a batch.

Run it after every config change, before restarting the daemon.

## `--debug`

Intended to enable verbose output from the pScheduler batch processor.

> **This flag currently has no effect, and debug output is always on.**
>
> Two independent issues combine: the flag is assigned to a local variable
> inside `main()` that nothing reads, and the check that would consume it tests
> a module-level *function* object, which is always truthy. The batch processor
> therefore always receives a debug callback, whether or not `--debug` is
> passed.
>
> Practically: expect batch-processor debug output on stderr regardless, and do
> not rely on this flag to turn it on or off.

## Running the daemon

Normally the daemon runs under systemd:

```bash
sudo systemctl status pssid-daemon
sudo systemctl restart pssid-daemon
sudo journalctl -u pssid-daemon -f
```

To run it by hand for diagnosis, stop the service first so two instances do not
contend for the same namespace:

```bash
sudo systemctl stop pssid-daemon
sudo pssid-daemon.py --validate
sudo systemctl start pssid-daemon
```

### Working directory matters

The daemon reads `batch_processor_format_template.j2` **relative to the current
working directory**. Run it from anywhere else and it raises

```
FileNotFoundError: batch_processor_format_template.j2
```

at the first batch — after startup has already appeared to succeed. Always `cd`
to the daemon's install directory first:

```bash
cd /usr/bin/pssid && sudo ./pssid-daemon.py --validate
```

The systemd unit sets this for you; only manual invocations are affected.
