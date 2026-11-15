# Integration with the pSSID GUI

v1 integration is **convention, not coupling**. Neither app breaks if the other
is absent.

## The daemon's file contract

The pSSID daemon opens **one config file per SSID profile**, with a fixed name
(`pssid-daemon.py`):

```
/etc/wpa_supplicant/wpa_supplicant_{ssid_profile}.conf
```

It runs `pssid-80211 -c <that file> -i <interface>` at batch time; the
`wpa_supplicant` *service* on probes is disabled and never restarted.

## Naming convention

One name is used at every layer: GUI **SSID profile** = credential-manager
**network** = credential-manager **bundle** (each bundle contains exactly that
one network). Probe provisioning then:

1. Pulls each bundle's render from this app (see
   `ansible/probe-pull-example.yml` or `scripts/pssid-credmgr-pull.sh`) and
   installs it as `/etc/wpa_supplicant/wpa_supplicant_<name>.conf`, `0600 root`.
2. Applies the pSSID daemon config from the GUI.

So when a GUI batch references SSID profile `eduroam`, the daemon finds
`wpa_supplicant_eduroam.conf` - rendered and delivered by this app - and
`wpa_supplicant` can join the SSIDs the batch tests. Multi-network bundles
remain useful outside the pSSID daemon (any consumer of a standard combined
`wpa_supplicant.conf`), but pSSID probes use the one-network-per-bundle form.

## Later: a GUI tab

The pSSID GUI can add a single nav link **"Wi-Fi Credentials"** that deep-links
to this app. With a shared OIDC provider the hop is seamless. True embedding
(iframe / shared components) is deliberately deferred.

## Deferred: variables-only endpoint

Some probe tooling already renders Jinja locally. A future variables-only
endpoint could serve derived variables (`psk_hex`, `password_nthash`, …) instead
of the fully rendered file. **v1 ships rendered-file pull only**, to keep
template logic in one audited place. Confirm with probe tooling owners before
freezing this contract.
