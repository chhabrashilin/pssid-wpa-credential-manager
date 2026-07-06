import { Router } from "express";
import type { AppContext } from "../context.js";
import { requireRole } from "../auth/middleware.js";
import { pingDb } from "../db.js";
import { asyncHandler } from "../util/errors.js";
import { getSettings } from "./settings.js";

/** Dashboard aggregate: counts, rotation warnings, recent audit, health (PRD 14.1). */
export function dashboardRouter(ctx: AppContext): Router {
  const r = Router();
  const { c } = ctx;

  r.get(
    "/",
    requireRole("read"),
    asyncHandler(async (_req, res) => {
      const settings = await getSettings(ctx);
      const warnMs = settings.rotation_warn_days * 86_400_000;
      const threshold = new Date(Date.now() - warnMs);

      const [networks, bundles, templates, tokens, recent, staleCreds] = await Promise.all([
        c.networks.countDocuments(),
        c.bundles.countDocuments(),
        c.templates.distinct("name").then((n) => n.length),
        c.tokens.countDocuments({ revoked_at: { $exists: false } }),
        c.audit.find().sort({ ts: -1 }).limit(10).toArray(),
        c.credentials
          .find({ status: "active", created_at: { $lt: threshold } })
          .sort({ created_at: 1 })
          .toArray(),
      ]);

      const rotationWarnings = staleCreds.map((cr) => ({
        network_name: cr.network_name,
        fingerprint: cr.fingerprint,
        age_days: Math.floor((Date.now() - cr.created_at.getTime()) / 86_400_000),
      }));

      res.json({
        counts: { networks, bundles, templates, tokens },
        rotation_warnings: rotationWarnings,
        recent_audit: recent.map(({ _id, ...e }) => e),
        health: { db: await pingDb(), kek: ctx.kek.length === 32 },
      });
    }),
  );

  return r;
}
