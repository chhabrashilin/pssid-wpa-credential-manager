import { Router } from "express";
import type { AppContext } from "../context.js";
import { pingDb } from "../db.js";
import { asyncHandler } from "../util/errors.js";

/**
 * GET /api/health — open endpoint. 200 only when the DB is reachable AND the
 * KEK is loaded (PRD 9.8). Never leaks detail beyond up/down booleans.
 */
export function healthRouter(ctx: AppContext): Router {
  const r = Router();
  r.get(
    "/",
    asyncHandler(async (_req, res) => {
      const db = await pingDb();
      const kek = ctx.kek.length === 32;
      const ok = db && kek;
      res.status(ok ? 200 : 503).json({
        status: ok ? "ok" : "degraded",
        db,
        kek,
        version: process.env.APP_VERSION ?? "1.0.0",
      });
    }),
  );
  return r;
}
