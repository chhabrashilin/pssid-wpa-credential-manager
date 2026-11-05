# wpa_supplicant

How a pSSID probe authenticates to the wireless networks it tests.

## The file contract

The pSSID daemon opens **one configuration file per SSID profile**, at a fixed
path:

```
/etc/wpa_supplicant/wpa_supplicant_<ssid_profile>.conf
```

`<ssid_profile>` is the **name** of the SSID profile as defined in the GUI - not
the SSID itself. A profile named `eduroam-5g` whose SSID is `eduroam` needs
`/etc/wpa_supplicant/wpa_supplicant_eduroam-5g.conf`.

At batch time the daemon runs:

```
ip netns exec pssid_<interface> \
  /usr/lib/exec/pssid/pssid-80211 -c <that file> -i <interface>
```

and again with `-d` to tear the association down afterwards.

> **The `wpa_supplicant` *service* is disabled on probes and must stay that way.**
> The daemon drives `pssid-80211` directly, per batch, inside a network
> namespace. Nothing should `systemctl restart wpa_supplicant` - after
> installing a new config there is nothing to restart, and the next batch picks
> the file up on its own.

### If the file is missing

The batch is **silently skipped**:

```python
if not os.path.exists(wpa_supplicant_conf_file):
    syslog.syslog(syslog.LOG_ERR, f"Error: ... does not exist.")
    return
```

No exception, no retry, no alert. The daemon keeps running and keeps scheduling
the batch; the batch does nothing, every time, forever. The probe remains
reachable and looks healthy.

Only two things reveal it: a `LOG_ERR` line in syslog that nothing aggregates,
and the absence of results in the archive.

Check for it directly on a probe:

```bash
# Which profiles does this probe's config declare?
jq -r '.batches[].ssid_profiles[]' /etc/pssid/pssid_config.json | sort -u

# Which conf files actually exist?
ls -1 /etc/wpa_supplicant/wpa_supplicant_*.conf
```

## Permissions

```
/etc/wpa_supplicant           0750  root:root
/etc/wpa_supplicant/*.conf    0600  root:root
```

These files contain **network-equivalent credentials**. Even when a config
carries no clear-text password, a derived form is enough to join the network:

- `psk=<64 hex>` authenticates to that WPA-PSK network on its own.
- `password=hash:<32 hex>` (the NT hash) authenticates to that PEAP/MSCHAPv2
  network on its own.

Deriving those forms keeps the *human-chosen* passphrase out of the file, which
limits credential reuse damage elsewhere. It does **not** make the file safe to
share. Rotation is the mitigation for a leak.

## File format

A standard `wpa_supplicant.conf`. Optional global block, then one `network={…}`
block.

### WPA-PSK

```
network={
    ssid="ExampleNet"
    scan_ssid=0
    key_mgmt=WPA-PSK
    psk=1a2b3c…                     # 64 hex chars, NOT the passphrase
    priority=5
}
```

Generate the hex form rather than storing the passphrase:

```bash
wpa_passphrase "ExampleNet" "the-passphrase"
```

This is `PBKDF2-SHA1(passphrase, ssid, 4096, 32)`. It is **SSID-specific** - the
same passphrase on a different SSID produces a different `psk`, so a config
cannot be copied between networks.

### PEAP / MSCHAPv2 (eduroam, most campus networks)

```
network={
    ssid="eduroam"
    scan_ssid=0
    key_mgmt=WPA-EAP
    eap=PEAP
    identity="probe@example.edu"
    password=hash:8846f7eaee8fb117ad06bdd830b7586c
    phase2="auth=MSCHAPV2"
    ca_cert="/etc/ssl/certs/example-ca.pem"
    priority=5
}
```

`hash:` takes the **NT hash** - `MD4(UTF-16LE(password))` - so the clear-text
password never appears in the file.

> OpenSSL 3 removed MD4 from its default provider, so `openssl dgst -md4` may
> fail. Python has it via `hashlib.new("md4")` only on builds that still expose
> it. The credential manager vendors a pure implementation for this reason.

### EAP-TLS

```
network={
    ssid="ExampleNet"
    key_mgmt=WPA-EAP
    eap=TLS
    identity="probe@example.edu"
    ca_cert="/etc/ssl/certs/example-ca.pem"
    client_cert="/etc/ssl/certs/probe.pem"
    private_key="/etc/ssl/private/probe.key"
    private_key_passwd="…"
}
```

Only paths appear in the config; the key material lives in the referenced files,
which need their own `0600 root` treatment.

### Open networks

```
network={
    ssid="GuestWiFi"
    key_mgmt=NONE
}
```

### Global block

If a profile needs global settings, they precede the `network` block:

```
ctrl_interface=/run/wpa_supplicant
update_config=0
country=US
```

## Getting the files onto probes

### Option A - pSSID Credential Manager (recommended)

Secrets are stored encrypted, rendered into derived forms, and pulled by the
probe over HTTPS with a scoped, expiring token. Nothing clear-text is ever
written to an inventory or a repository.

```bash
CREDMGR_TOKEN=… pssid-credmgr-pull.sh https://credmgr.example.edu eduroam
```

Installs `/etc/wpa_supplicant/wpa_supplicant_eduroam.conf` as `0600 root`, and
uses `If-None-Match` so an unchanged render is a no-op.

The naming convention ties the layers together - one name at every level:

```
GUI SSID profile name  ==  credential-manager network  ==  credential-manager bundle
```

with one network per bundle, because the daemon wants one file per profile.

### Option B - Ansible with a vaulted variables file

The older workflow: write `wpa_supplicant_profiles.yml` containing clear-text
credentials, encrypt it with `ansible-vault`, and render it onto probes.

If you use this, note two things:

1. The vault password file is the whole security boundary. Some published
   instructions suggest `chmod 644 .vault_pass.txt` and `chmod 755 -R` over the
   playbook tree - that makes the vault password readable by every local user,
   next to the vault it opens, which removes the protection entirely. Keep it
   `0600`, owned by the user running Ansible.
2. The clear-text file exists on the controller before encryption, and in shell
   history. Shred it (`shred -u`) once the vault file is written.

### Option C - by hand

Acceptable for a single lab probe:

```bash
sudo install -d -m 0750 -o root -g root /etc/wpa_supplicant
sudo install -m 0600 -o root -g root myprofile.conf \
     /etc/wpa_supplicant/wpa_supplicant_myprofile.conf
```

## Verifying a config

Check it parses before relying on it:

```bash
sudo timeout 5 wpa_supplicant -c /etc/wpa_supplicant/wpa_supplicant_eduroam.conf \
     -i lo -D wired
sudo pkill -x wpa_supplicant
```

Two notes: `wpa_supplicant` never exits on its own, hence `timeout`; and use
`pkill -x` (exact name) rather than `pkill -f`, which would match your own
command line and kill the terminal.

Successful parsing does **not** mean the credentials are correct - only that the
syntax is valid.

## Troubleshooting

**Batch produces no results, probe otherwise healthy.**
The conf file is missing. See "If the file is missing" above. Confirm the
filename matches the *profile name* exactly, including case and hyphens.

**`wpa_supplicant` reports "line N: unknown network field".**
Usually a stray key, or a value that needed quoting. `ssid`, `identity`,
`phase2` and file paths take quotes; `psk` (hex form), `priority`, `scan_ssid`
and `key_mgmt` do not.

**Association fails but the file parses.**
Credentials, or CA trust. For PEAP, confirm the `ca_cert` path exists on the
probe and that the `identity` realm matches what the RADIUS server expects.

**It worked, then stopped after a credential rotation.**
The probe still holds the old render. Re-pull it. With the credential manager,
check that a new render was produced after the rotation - storing a new secret
does not by itself update the rendered file.

**A file exists but is zero bytes.**
That is not a config. Some provisioning paths ship an empty placeholder profile;
`wpa_supplicant` will fail on it exactly as if it were absent.
