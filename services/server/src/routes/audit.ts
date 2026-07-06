import { Router } from "express";
import type { Filter } from "mongodb";
import type { AppContext } from "../context.js";
import type { AuditEventDoc } from "../models/types.js";
import { requireRole } from "../auth/middleware.js";
import { asyncHandler } from "../util/errors.js";

/** Read-only audit browsing with filters + CSV export (PRD 9.7). */
export function auditRouter(ctx: AppContext): Router {
  const r = Router();
  const { c } = ctx;

  function buildFilter(q: Record<string, unknown>): Filter<AuditEventDoc> {
    const f: Filter<AuditEventDoc> = {};
    if (q.actor) f.actor = String(q.actor);
    if (q.action) f.action = String(q.action) as AuditEventDoc["action"];
    if (q.object) f.object = String(q.object);
    if (q.from || q.to) {
      f.ts = {};
      if (q.from) (f.ts as Record<string, Date>).$gte = new Date(String(q.from));
      if (q.to) (f.ts as Record<string, Date>).$lte = new Date(String(q.to));
    }
    return f;
  }

  r.get(
    "/",
    requireRole("read"),
    asyncHandler(async (req, res) => {
      const filter = buildFilter(req.query);
      const limit = Math.min(parseInt(String(req.query.limit ?? "200"), 10) || 200, 1000);
      const events = await c.audit.find(filter).sort({ ts: -1 }).limit(limit).toArray();
      res.json(events.map(({ _id, ...e }) => e));
    }),
  );

  r.get(
    "/export.csv",
    requireRole("read"),
    asyncHandler(async (req, res) => {
      const filter = buildFilter(req.query);
      const events = await c.audit.find(filter).sort({ ts: -1 }).limit(10_000).toArray();
      const header = "ts,actor,actor_type,action,object,meta\n";
      const rows = events
        .map((e) => {
          const meta = JSON.stringify(e.meta).replace(/"/g, '""');
          return `${e.ts.toISOString()},${csv(e.actor)},${e.actor_type},${e.action},${csv(e.object)},"${meta}"`;
        })
        .join("\n");
      res.setHeader("Content-Disposition", 'attachment; filename="audit.csv"');
      res.type("text/csv").send(header + rows + "\n");
    }),
  );

  return r;
}

function csv(v: string): string {
  return /[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v;
}
