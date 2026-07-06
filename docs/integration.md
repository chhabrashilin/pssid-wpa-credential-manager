# Integration with the pSSID GUI

v1 integration is **convention, not coupling**. Neither app breaks if the other
is absent.

## Naming convention

A pSSID GUI **SSID profile** name should match a credential-manager **network**
name (e.g. `mwireless`). Probe provisioning then:

1. Pulls the bundle for that probe class from this app (see
   `ansible/probe-pull-example.yml`) → installs `wpa_supplicant.conf` `0600 root`.
2. Applies the pSSID daemon config from the GUI.

So `wpa_supplicant` can join the SSIDs that the GUI's batches will test.

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
