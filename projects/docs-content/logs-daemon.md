# Daemon logs

Where the pSSID daemon writes, and how to read it.

## Two log streams

The daemon produces two distinct things, and confusing them wastes time.

| Stream | Ident | Facility | Contains |
|---|---|---|---|
| **Operational** | `pssid` | set at startup (`--facility`, default `local0`) | scheduling, namespace setup, layer 2/3, errors |
| **Measurement** | `pssid` | per-test, from the batch processor | actual test results, archived |

Operational messages tell you whether the probe is *working*. Measurement
records are the *output*. A probe can be perfectly healthy operationally and
produce no measurements - that is the most common failure, and only the
operational stream shows why.

The daemon also prints to stdout/stderr. Under systemd that lands in the
journal; run by hand it goes to your terminal.

## Reading them

```bash
# Everything from the unit, following
sudo journalctl -u pssid-daemon -f

# Errors only, since boot
sudo journalctl -u pssid-daemon -p err -b

# By syslog ident, which catches messages from any invocation
sudo journalctl -t pssid -n 100

# On a system with rsyslog writing files
sudo tail -f /var/log/syslog | grep pssid
```

## What normal operation looks like

At startup, once per batch the probe owns:

```
Host probe-1 identified in hosts
Host probe-1 identified in rpi4 group
Schedule batch 'batch_A', earlist next run time: 2026-08-19 14:32:00, cron expression: */2 * * * *
```

Then, per run:

```
Running batch at 2026-08-19 14:32:00 of name of batch_A with cron_expression */2 * * * *
Create namespace pssid_wlan0
Add interface wlan0 to namespace pssid_wlan0
pssid-80211: <association output>
pssid-dhcp: <lease output>
pssid-80211 teardown: <output>
```

A batch that completes leaves a matching teardown line for each build line. A
run that stops partway through is the useful signal.

## Messages that matter

### `No host with name '<hostname>' found.`

**Fatal - the daemon exits 1.** The probe's hostname does not match any `hosts`
entry in the config.

```bash
hostname                                                    # what the probe calls itself
jq -r '.hosts[].name' /etc/pssid/pssid_config.json          # what the config expects
```

Fix one or the other. Note the daemon uses `socket.gethostname()`, which may
differ from the FQDN.

### `Error: wpa_supplicant conf file … does not exist.`

**The most important line in this document.**

The batch is skipped and the daemon carries on. Nothing retries, nothing
escalates, and the probe stays up looking healthy while testing nothing.

```bash
# Which profiles are expected?
jq -r '.batches[].ssid_profiles[]' /etc/pssid/pssid_config.json | sort -u
# Which files exist?
ls -1 /etc/wpa_supplicant/wpa_supplicant_*.conf
```

The filename must match the SSID **profile name** exactly. See
[wpa_supplicant](config-wpa-supplicant.md).

### `Batch '<name>' has unresolved variables.`

A `$variable` in the batch had no matching metadata, so the batch is invalid and
will not run. Check the `data` block on the host entry and on any group it
belongs to.

### `Batch '<name>' is invalid.`

A referenced job or test does not exist, or the batch has no SSID profiles.
Run `pssid-daemon.py --validate` for the specific cause.

### `No cron expression found for schedule: <name>`

The batch references a schedule that is not defined. That schedule is skipped;
if it was the only one, the batch is never queued.

### `Cannot schedule a batch name <name>, batch does not have a schedule.`

The batch resolved to no usable schedule at all. It is loaded, valid, and will
never run.

### `Error in building layer 2`

`pssid-80211` failed to associate. The config file exists and parsed, but the
association did not complete. Usual causes: wrong credentials, missing or
untrusted `ca_cert`, the network out of range, or the interface not actually in
the namespace.

### `Error building layer 3`

Association succeeded, DHCP did not. The probe joined the network but got no
address.

### `No batch found.`

No batch resolved for this probe. Note the daemon **does not exit** here - it
continues and schedules nothing, so the process stays up doing no work. Treat
this line as equivalent to a failure even though the daemon does not.

## Diagnosing "the probe produces no results"

In order, because each step rules out the ones after it:

```bash
# 1. Is the daemon even running?
sudo systemctl status pssid-daemon

# 2. Did it identify this host and schedule anything?
sudo journalctl -u pssid-daemon -b | grep -E "identified|Schedule batch|No host|No batch"

# 3. Does the config validate?
cd /usr/bin/pssid && sudo ./pssid-daemon.py --validate

# 4. Are the credential files present?  <- the usual answer
jq -r '.batches[].ssid_profiles[]' /etc/pssid/pssid_config.json | sort -u
ls -l /etc/wpa_supplicant/wpa_supplicant_*.conf

# 5. Are batches firing?
sudo journalctl -u pssid-daemon --since "1 hour ago" | grep "Running batch"

# 6. Are they getting through layer 2 and 3?
sudo journalctl -u pssid-daemon --since "1 hour ago" | grep -E "built layer|Error"
```

Step 4 is the most common cause and the least visible, because the daemon
reports it once at `LOG_ERR` and then behaves normally forever after.

`pssid-probe-health` automates steps 1 through 4 and exits non-zero when the
probe cannot test.

## Log volume

Every batch logs several lines, and a two-minute schedule means roughly 700 runs
a day. Make sure log rotation is configured, particularly if `local0` is also
receiving measurement records.

```bash
sudo journalctl --disk-usage
sudo journalctl --vacuum-time=14d
```
