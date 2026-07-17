# Security model

## Envelope encryption (R1)

Each secret gets a random 256-bit **data key (DEK)**. The payload is encrypted
with AES-256-GCM under the DEK. The DEK is then wrapped (also AES-256-GCM) under
the **master key (KEK)**.

```
payload  --AES-256-GCM(DEK)-->  payload_ct, payload_iv, payload_tag
DEK      --AES-256-GCM(KEK)-->  dek_wrapped  ( iv || tag || ciphertext )
```

- **KEK source** (in order): `KEK_FILE` (installer writes it `0400`), else
  `KEK_BASE64` (container platforms). The process fails to start if neither
  resolves to exactly 32 bytes.
- **KEK rotation** re-wraps every DEK under the new KEK without re-encrypting
  (or decrypting) the payloads. See `rewrapDek` and its tests.

## Write-only secrets (R2)

`GET` on any credential returns metadata only: `fingerprint` (first 8 hex of
SHA-256 of the raw secret), `version`, `created_by/at`. There is deliberately no
reveal endpoint. The browser can *write* a secret and *confirm* it by
fingerprint, never read it back.

## Derived, non-clear-text forms (R3)

| Security type | Rendered form | Derivation |
|---------------|---------------|------------|
| WPA-PSK | `psk=<64 hex>` | `PBKDF2-SHA1(passphrase, ssid, 4096, 32)` — identical to `wpa_passphrase` |
| PEAP/MSCHAPv2 | `password=hash:<32 hex>` | `MD4(UTF-16LE(password))` (the NT hash) |
| EAP-TLS | file paths | no password rendered; cert/key delivered as artifacts |

The human passphrase/password never appears in a rendered file.

### MD4 note

OpenSSL 3 dropped MD4 from the default provider, so `crypto.createHash("md4")`
is unavailable on many Node builds. We **vendor a pure-JS MD4**
(`src/crypto/md4.ts`), verified against the RFC 1320 vectors and the canonical
NT hash (`MD4(UTF-16LE("password")) = 8846f7ea…`).

## Honesty requirement (R4)

The derived forms are **still secrets**. A stolen 64-hex PSK or NT hash
authenticates to that one network — they are *network-equivalent credentials*.

What R3 guarantees:
1. The human-chosen passphrase/password is never disclosed (no credential-reuse
   blast radius across other systems).
2. Casual reading of files on a probe yields no clear text.

What it does **not** guarantee: that a rendered file is safe to share. It is
not. **Rotation (R6) is the real mitigation** for any leak. The UI never claims
otherwise.

## Delivery hygiene (R5)

- Renders are served only over HTTPS to authenticated machine tokens.
- Responses carry `Cache-Control: no-store`.
- On-probe placement: `wpa_supplicant_<profile>.conf` root-owned `0600`,
  directory `/etc/wpa_supplicant` `0750` — one file per SSID profile, the
  name the pSSID daemon opens (see `ansible/probe-pull-example.yml` and
  `docs/integration.md`).

## Tokens

Machine tokens are **read-only**, **scoped to specific bundles**, **expiring**
(default 1 year), and **revocable**. Only the SHA-256 of the token is stored;
the value is shown exactly once at creation.

## Audit (R7)

Every sensitive action is appended to `audit_events` (create/view/change/rotate/
fetch, token create/revoke, auth denials, machine pulls). Meta carries
fingerprints and versions only; a defensive scrubber drops any secret-looking
key. Audit is append-only — no API path updates or deletes rows.

## Backups

`mongodump` output contains only encrypted payloads. Restoring it **without**
the KEK yields nothing usable. **Back up `secrets/master.key` separately** — a
dump plus the KEK together reconstitute all secrets, so keep them on different
media with different access control.
