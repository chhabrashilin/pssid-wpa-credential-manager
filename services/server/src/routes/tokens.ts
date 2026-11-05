import crypto from "node:crypto";
import { Router } from "express";
import type { AppContext } from "../context.js";
import type { TokenDoc } from "../models/types.js";
import { requireRole } from "../auth/middleware.js";
import { generateToken, tokenHash } from "../crypto/index.js";
import { record } from "../services/audit.js";
import { asyncHandler, badRequest, notFound } from "../util/errors.js";
import { parse, tokenCreateSchema } from "../util/validate.js";

/** Metadata view of a token - never includes hash or value. */
function tokenView(t: TokenDoc) {
  return {
    id: t.id,
    name: t.name,
    scopes: t.scopes,
    expires_at: t.expires_at,
    created_by: t.created_by,
    created_at: t.created_at,
    revoked_at: t.revoked_at ?? null,
    last_used_at: t.last_used_at ?? null,
    status: t.revoked_at ? "revoked" : t.expires_at.getTime() <= Date.now() ? "expired" : "active",
  };
}

export function tokensRouter(ctx: AppContext): Router {
  const r = Router();
  const { c } = ctx;

  // Token management is a write-role concern (PRD 9.6 API sketch).
  r.get(
    "/",
    requireRole("write"),
    asyncHandler(async (_req, res) => {
      const tokens = await c.tokens.find().sort({ created_at: -1 }).toArray();
      res.json(tokens.map(tokenView));
    }),
  );

  r.post(
    "/",
    requireRole("write"),
    asyncHandler(async (req, res) => {
      const input = parse(tokenCreateSchema, req.body);
      // Every scoped bundle must exist.
      for (const scope of input.scopes) {
        if (!(await c.bundles.findOne({ name: scope }))) {
          throw badRequest(`Scope references unknown bundle '${scope}'`);
        }
      }
      const value = generateToken();
      const doc: TokenDoc = {
        id: crypto.randomUUID(),
        name: input.name,
        hash: tokenHash(value),
        scopes: input.scopes,
        expires_at: new Date(Date.now() + input.expires_in_days * 86_400_000),
        created_by: req.principal!.actor,
        created_at: new Date(),
      };
      await c.tokens.insertOne(doc);
      await record(c, req.principal!, "token.create", doc.id, {
        name: doc.name,
        scopes: doc.scopes,
        expires_at: doc.expires_at,
      });
      // The value is shown exactly ONCE (PRD 9.5).
      res.status(201).json({ ...tokenView(doc), token: value });
    }),
  );

  r.delete(
    "/:id",
    requireRole("write"),
    asyncHandler(async (req, res) => {
      const t = await c.tokens.findOne({ id: req.params.id! });
      if (!t) throw notFound("Token not found");
      if (!t.revoked_at) {
        await c.tokens.updateOne({ id: req.params.id! }, { $set: { revoked_at: new Date() } });
        await record(c, req.principal!, "token.revoke", req.params.id!, { name: t.name });
      }
      res.status(204).end();
    }),
  );

  return r;
}
