# API reference

All endpoints are under `/api/v1` and speak JSON unless noted. Errors are always
JSON `{ "message": "..." }` (400/401/403/404/409); never HTML, never a stack
trace. Roles: **read**, **write**, **token** (machine pull only).

| Method | Path | Access | Notes |
|--------|------|--------|-------|
| GET | `/health` | open | `{status, db, kek, version}`; 200 only when DB up **and** KEK loaded |
| GET | `/me` | any | current caller `{actor, role, sso_enabled}` |
| GET | `/dashboard` | read | counts, rotation warnings, recent audit, health |
| GET | `/networks` | read | list (no secrets) |
| GET | `/networks/:name` | read | one network (no secret) |
| POST | `/networks` | write | create |
| PUT | `/networks/:name` | write | update (never credentials) |
| DELETE | `/networks/:name` | write | 409 if referenced by a bundle |
| PUT | `/networks/:name/credential` | write | set/rotate secret (write-only; returns metadata only) |
| POST | `/networks/:name/credential/rollback/:version` | write | re-activate an old version as a new version |
| GET | `/networks/:name/credential/versions` | read | version history (fingerprints only) |
| GET | `/templates` | read | one row per name w/ version summary |
| GET | `/templates/:name?version=N` | read | body of a version |
| GET | `/templates/:name/versions` | read | all versions |
| POST | `/templates` | write | new draft version (lint-checked) |
| POST | `/templates/:name/validate` | read | validate without saving |
| POST | `/templates/:name/activate` | write | validate + activate (blocks on errors) |
| GET | `/templates/:name/diff?from&to` | read | body diff |
| GET | `/bundles` | read | list |
| POST | `/bundles` | write | create |
| PUT | `/bundles/:name` | write | update |
| DELETE | `/bundles/:name` | write | 409 if referenced by a token |
| GET | `/bundles/:name/preview` | read | redacted `text/plain` preview |
| POST | `/bundles/:name/render` | write | produce + store an encrypted render, bump version |
| GET | `/bundles/:name/renders` | read | render history (metadata) |
| GET | `/bundles/:name/diff?from&to` | read | redacted diff of stored renders |
| **GET** | **`/bundles/:name/render`** | **token** | **raw `.conf` machine pull** (see below) |
| GET | `/tokens` | write | metadata only |
| POST | `/tokens` | write | create; returns `token` value **once** |
| DELETE | `/tokens/:id` | write | revoke |
| GET | `/audit?actor&action&object&from&to&limit` | read | filterable |
| GET | `/audit/export.csv?...` | read | CSV export |
| GET | `/settings` / PUT | read / write | rotation threshold + read-only SSO/role view |

## Machine pull

```
GET /api/v1/bundles/:name/render
Authorization: Bearer <token>
If-None-Match: "<fingerprint>"      (optional)
```

Response `200 text/plain` with headers:

```
X-Render-Version: 3
X-Render-Fingerprint: 3fa2c19b
ETag: "3fa2c19b"
Cache-Control: no-store
```

If the supplied `If-None-Match` matches the current render fingerprint, returns
`304 Not Modified` with no body - provisioning skips the unchanged config.

The token must be non-revoked, unexpired, and scoped to `:name`; otherwise
`401`/`403` (all denials audited).

For pSSID probes, install the body as
`/etc/wpa_supplicant/wpa_supplicant_<bundle>.conf` (`0600 root`) - the daemon
opens one file per SSID profile under exactly that name; see
[`integration.md`](integration.md).

## Template variable contract

Templates receive: `ssid`, `name`, `security`, `priority`, `scan_ssid`,
`psk_hex`, `identity`, `password_nthash`, `ca_cert`, `client_cert`,
`private_key`, plus every non-secret extra variable on the network. Secrets are
exposed **only** in derived form. Undefined variables fail the render (fail
closed). Includes/inheritance and attribute/prototype access are rejected.
