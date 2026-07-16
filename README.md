# pSSID Credential Manager

A standalone web app that manages `wpa_supplicant` configuration templates and
the Wi-Fi credentials inside them, so wireless secrets are **stored encrypted**,
**delivered to probes at provision time**, and **never exist in clear text on a
host machine**.

It is a sibling to the [pSSID GUI](https://github.com/) (which manages *what*
probes test); this app manages *how* a probe authenticates to the SSIDs it
tests. See [`PRD`](docs/PRD.md) for the full product spec.

---

## What it does

- **One encrypted registry** of wireless networks and their credentials
  (WPA-PSK, PEAP/MSCHAPv2, EAP-TLS), with envelope encryption at rest.
- **Browser-managed Jinja templates** for `wpa_supplicant` blocks: create,
  version, validate, preview (redacted), diff.
- **Renders** per-bundle `wpa_supplicant.conf` using **derived, non-clear-text
  credential forms** (`psk=<64-hex>`, `password=hash:<NT hash>`).
- **Machine-pull delivery API** with scoped, expiring bearer tokens and an
  `If-None-Match`/`304` flow for idempotent provisioning.
- **Full audit trail** and role-based access (OIDC groups → read/write).

## The no-clear-text guarantees

| Rule | Guarantee |
|------|-----------|
| **R1** | Every secret is AES-256-GCM encrypted under a per-secret data key, wrapped by a master key (KEK). |
| **R2** | Secrets are **write-only**: the API never returns a value — only a fingerprint, version, and age. There is no "reveal". |
| **R3** | Rendered files use derived forms wherever the protocol allows: PBKDF2 PSK hex and MSCHAPv2 NT hash. The human passphrase/password never leaves the manager. |
| **R4** | **Honest messaging**: the derived forms are still *network-equivalent* secrets. A rendered file is never "safe to share". Rotation limits leak damage. |
| **R5** | Renders are HTTPS + token only, `Cache-Control: no-store`, and documented for `0600 root` on-probe placement. |
| **R7** | No secret (raw or derived) ever appears in logs, audit payloads, or the browser. Preview shows `<redacted:fp …>`. |

See [`docs/security.md`](docs/security.md) for the threat model and honest
limitations.

---

## Quick start (Docker)

```bash
./install.sh            # interactive: hostname, TLS, SSO; generates KEK + certs + .env
# or non-interactive:
HOSTNAME=credmgr.local TLS=self-signed SSO=false ./install.sh -y
```

Then open `https://<hostname>/`. Health: `https://<hostname>/api/health`.

> With SSO off, the app is **read-only** unless you set `OPEN_WRITE=true` in
> `.env` (lab mode).

### From-scratch (Ansible)

```bash
ansible-galaxy collection install -r ansible/requirements.yml   # once
cp ansible/inventory.ini.example ansible/inventory.ini          # edit host
ansible-playbook -i ansible/inventory.ini ansible/site.yml
```

## Development

```bash
make install          # install workspace deps
make dev-server       # API on :8080 (needs Mongo + a KEK)
make dev-client       # Vite dev server on :5173 (proxies /api)
make test             # crypto / derivation / authz / template suites
make smoke            # full end-to-end journey against a running stack
```

Run a local KEK for dev:

```bash
mkdir -p secrets && head -c 32 /dev/urandom > secrets/master.key
KEK_FILE=secrets/master.key OPEN_WRITE=true make dev-server
```

## Delivering configs to probes

The pSSID daemon reads one file per SSID profile
(`/etc/wpa_supplicant/wpa_supplicant_{profile}.conf`), so define one bundle per
profile — bundle name = GUI SSID-profile name = network name — and the pull
tooling installs each render under the name the daemon expects
(see [`docs/integration.md`](docs/integration.md)):

```bash
# Ansible (idempotent — 304 on unchanged render):
ansible-playbook -i probes.ini ansible/probe-pull-example.yml \
  -e credmgr_base=https://credmgr.example.edu \
  -e '{"credmgr_bundles": ["eduroam", "MWireless"]}' -e credmgr_token=$CREDMGR_TOKEN

# or the shell helper (installs wpa_supplicant_eduroam.conf):
CREDMGR_TOKEN=xxx scripts/pssid-credmgr-pull.sh https://credmgr.example.edu eduroam
```

## Backups

```bash
scripts/backup.sh ./backups
```

The dump contains only encrypted payloads — **useless without the KEK**. Back
up `secrets/master.key` **separately** from database dumps.

## Architecture

```
services/server   Node 18+ / Express / TypeScript API (crypto, routes, auth, audit)
services/client   Vue 3 + Vite + Pinia SPA (served by the server in prod)
ansible/          site.yml (deploy) + probe-pull-example.yml
config/           nginx.conf, roles.json (OIDC group → role map)
scripts/          smoke.sh, backup.sh, pssid-credmgr-pull.sh
docs/             PRD, security model, API reference
```

Integration with the pSSID GUI is by **convention** (a GUI SSID-profile name
matches a credential-manager network name) — see [`docs/integration.md`](docs/integration.md).

## License

MIT
