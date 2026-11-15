import type { Collections } from "../db.js";
import type { AuditAction, AuditEventDoc } from "../models/types.js";
import type { Principal } from "../auth/principal.js";

/**
 * Append-only audit log (PRD 9.7). Meta must NEVER contain secret values -
 * fingerprints only. This module is the single writer; nothing exposes an
 * update/delete path for audit rows.
 */
export async function record(
  c: Collections,
  principal: Pick<Principal, "actor" | "actorType">,
  action: AuditAction,
  object: string,
  meta: Record<string, unknown> = {},
): Promise<void> {
  const event: AuditEventDoc = {
    ts: new Date(),
    actor: principal.actor,
    actor_type: principal.actorType,
    action,
    object,
    meta: scrub(meta),
  };
  await c.audit.insertOne(event);
}

/**
 * Defense-in-depth: drop any field whose key looks like it might carry a
 * secret, in case a caller passes the wrong thing. Fingerprints/versions pass.
 */
const FORBIDDEN_KEYS = /pass(word|phrase)?|secret|psk|identity|key|token|hash(?!:)/i;

function scrub(meta: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(meta)) {
    if (k === "fingerprint" || k === "version" || k === "render_version") {
      out[k] = v;
      continue;
    }
    if (FORBIDDEN_KEYS.test(k)) {
      out[k] = "[redacted]";
      continue;
    }
    out[k] = v;
  }
  return out;
}
