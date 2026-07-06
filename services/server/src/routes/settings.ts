import { Router } from "express";
import type { AppContext } from "../context.js";
import type { SettingsDoc } from "../models/types.js";
import { requireRole } from "../auth/middleware.js";
import { asyncHandler } from "../util/errors.js";
import { z } from "zod";
import { parse } from "../util/validate.js";

async function getSettings(ctx: AppContext): Promise<SettingsDoc> {
  const existing = await ctx.c.settings.findOne({ _id: "app" });
  if (existing) return existing;
  const seed: SettingsDoc = {
    _id: "app",
    rotation_warn_days: ctx.cfg.rotationWarnDays,
    kek_version: 1,
  };
  await ctx.c.settings.insertOne(seed);
  return seed;
}

const updateSchema = z.object({
  rotation_warn_days: z.number().int().min(1).max(3650),
});

export function settingsRouter(ctx: AppContext): Router {
  const r = Router();

  r.get(
    "/",
    requireRole("read"),
    asyncHandler(async (_req, res) => {
      const s = await getSettings(ctx);
      res.json({
        rotation_warn_days: s.rotation_warn_days,
        kek_version: s.kek_version,
        sso_enabled: ctx.cfg.ssoEnabled,
        open_write: ctx.cfg.openWrite,
        // Read-only view of the group→role mapping (PRD 9.6 / Settings page).
        role_map: ctx.roleMap.groups,
        version: process.env.APP_VERSION ?? "1.0.0",
      });
    }),
  );

  r.put(
    "/",
    requireRole("write"),
    asyncHandler(async (req, res) => {
      const input = parse(updateSchema, req.body);
      await ctx.c.settings.updateOne(
        { _id: "app" },
        { $set: { rotation_warn_days: input.rotation_warn_days } },
        { upsert: true },
      );
      const s = await getSettings(ctx);
      res.json({ rotation_warn_days: s.rotation_warn_days });
    }),
  );

  return r;
}

export { getSettings };
