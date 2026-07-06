import type { NextFunction, Request, Response } from "express";
import type { Collections } from "../db.js";
import { tokenHash } from "../crypto/fingerprint.js";
import { record } from "../services/audit.js";
import { forbidden, unauthorized } from "../util/errors.js";

/**
 * Machine-token authentication for the render pull endpoint (PRD 9.5).
 * Tokens are read-only, scoped to specific bundles, expiring and revocable.
 * The token value is never stored — only its SHA-256.
 */
export function requireToken(c: Collections) {
  return async (req: Request, _res: Response, next: NextFunction): Promise<void> => {
    try {
      const header = req.header("authorization") ?? "";
      const match = /^Bearer\s+(.+)$/i.exec(header.trim());
      if (!match) {
        await record(c, { actor: "anonymous", actorType: "token" }, "auth.denied", req.path, {
          reason: "missing_bearer",
        });
        return next(unauthorized("Bearer token required"));
      }
      const value = match[1]!.trim();
      const doc = await c.tokens.findOne({ hash: tokenHash(value) });

      if (!doc || doc.revoked_at) {
        await record(c, { actor: "anonymous", actorType: "token" }, "auth.denied", req.path, {
          reason: "invalid_or_revoked",
        });
        return next(unauthorized("Invalid token"));
      }
      if (doc.expires_at.getTime() <= Date.now()) {
        await record(c, { actor: doc.id, actorType: "token" }, "auth.denied", req.path, {
          reason: "expired",
        });
        return next(unauthorized("Token expired"));
      }

      const bundleName = req.params.name;
      if (bundleName && !doc.scopes.includes(bundleName)) {
        await record(c, { actor: doc.id, actorType: "token" }, "auth.denied", req.path, {
          reason: "out_of_scope",
          bundle: bundleName,
        });
        return next(forbidden("Token not scoped for this bundle"));
      }

      await c.tokens.updateOne({ id: doc.id }, { $set: { last_used_at: new Date() } });
      req.principal = {
        actor: doc.id,
        actorType: "token",
        role: "read",
        tokenScopes: doc.scopes,
      };
      next();
    } catch (err) {
      next(err);
    }
  };
}
