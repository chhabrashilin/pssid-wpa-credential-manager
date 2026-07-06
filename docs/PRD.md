# PRD: pSSID Credential Manager

> This is the canonical product spec the implementation was built from. It is
> reproduced here so an engineer with no prior context can understand intent.
> For the security model see [`security.md`](security.md); for endpoints see
> [`api.md`](api.md); for GUI integration see [`integration.md`](integration.md).

A standalone web application that manages `wpa_supplicant` configuration
templates and the Wi-Fi credentials inside them, so that wireless secrets are
stored encrypted, delivered to probe machines at provision time, and never
exist in clear text on a host machine.

## Goals

- **G1** One encrypted registry of wireless networks and their credentials.
- **G2** Manage `wpa_supplicant` Jinja templates in the browser: create, edit,
  version, validate, preview with redaction, diff.
- **G3** Render per-network (and per-host) `.conf` by combining template +
  stored credentials, using non-clear-text credential forms.
- **G4** Deliver rendered configs at provision time through an authenticated
  machine API (pull), so no secret is checked into any repo or inventory.
- **G5** No clear text on the host machine; secrets encrypted at rest.
- **G6** Full audit of who created/viewed/changed/rotated/fetched a secret.
- **G7** Same ops bar as the pSSID GUI: one-command install, HTTPS, optional
  OIDC SSO, Docker Compose, backups, health endpoint.

## Core concepts

- **Network** — a wireless network to join (SSID + unique name), with a
  security type: `wpa-psk`, `wpa-eap-peap-mschapv2`, `eap-tls`, `open`.
- **Credential** — versioned secret material for a network. Only the latest
  version renders; older versions kept encrypted for audit/rollback.
- **Template** — a versioned Jinja template producing a `network={...}` block.
- **Bundle** — a named, ordered set of networks rendered into one
  `wpa_supplicant.conf` for a class of probes.
- **Render** — the act of producing final `.conf` text with derived secrets.
- **Machine token** — a scoped, read-only, expiring API token for pull.

## The no-clear-text rules

- **R1** Envelope encryption: per-secret AES-256-GCM data key, wrapped by a
  master key (KEK) from a file or env; KEK rotation re-wraps data keys only.
- **R2** Secrets are write-only in the API; GET returns metadata + fingerprint,
  never the value. No reveal feature.
- **R3** Rendered output uses derived forms: WPA-PSK → `psk=<64-hex>`
  (PBKDF2-SHA1, 4096, 32); PEAP/MSCHAPv2 → `password=hash:<NT hash>`; EAP-TLS →
  file paths only.
- **R4** Honesty: derived forms are still network-equivalent secrets; the
  rendered file is never "safe to share". Rotation is the mitigation.
- **R5** HTTPS + token pull, `Cache-Control: no-store`, on-probe `0600 root`.
- **R6** Rotation supersedes the old version, bumps the render version, audited.
- **R7** No secret (raw or derived) in logs, errors, audit, or the DOM; preview
  shows `<redacted:fp …>`.

## Milestones (all delivered)

- **M1** Core vault: networks + credentials CRUD, envelope encryption,
  write-only API, fingerprints, health, crypto + authz tests.
- **M2** Templates + rendering: Jinja sandbox, starter templates, redacted
  preview, derived forms with vector tests.
- **M3** Bundles + delivery: renders, versioning, diff, machine tokens, pull API
  with 304 flow, Ansible pull example.
- **M4** Ship: SSO + roles, audit page, installer + Ansible roles, backups,
  docs, smoke test, dark mode.

## Acceptance criteria

- [x] Define a PEAP network, store identity+password once, never see the
      password again in any UI/API response.
- [x] `mongodump` contains no recoverable secret without the separate KEK.
- [x] A render contains `password=hash:…` / `psk=<64 hex>` and no clear text;
      preview shows redacted placeholders.
- [x] An Ansible task with a machine token installs the file `0600 root`; a
      re-run with an unchanged render is a `304` no-op.
- [x] Rotating a credential produces a new render version; the pull picks it up;
      audit shows who rotated and which machine pulled.
- [x] A read-role user browses everything but cannot write and never receives a
      secret or token value; denials are audited.
- [x] `make test` runs crypto/derivation/authz/template suites green;
      `make smoke` walks the full journey against a running stack.
- [x] `./install.sh` (or `ansible-playbook site.yml`) takes a fresh box to a
      working HTTPS deployment in one command.

## Non-goals (v1)

Not a general secrets vault; not a certificate authority (EAP-TLS certs are
stored/templated, not issued); no changes to the pSSID daemon/GUI; not a
RADIUS/network-side tool; single-tenant.
