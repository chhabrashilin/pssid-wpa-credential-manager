import { Router } from "express";
import type { AppContext } from "../context.js";
import type { TemplateDoc } from "../models/types.js";
import { requireRole } from "../auth/middleware.js";
import { record } from "../services/audit.js";
import { lintTemplate, validateTemplateBody } from "../services/template.js";
import { asyncHandler, badRequest, notFound } from "../util/errors.js";
import { parse, templateCreateSchema } from "../util/validate.js";

export function templatesRouter(ctx: AppContext): Router {
  const r = Router();
  const { c } = ctx;

  // --- List (one row per template name, with version summary) ---
  r.get(
    "/",
    requireRole("read"),
    asyncHandler(async (_req, res) => {
      const all = await c.templates.find().sort({ name: 1, version: -1 }).toArray();
      const byName = new Map<string, { name: string; latest_version: number; active_version: number | null; versions: number }>();
      for (const t of all) {
        const cur = byName.get(t.name);
        if (!cur) {
          byName.set(t.name, {
            name: t.name,
            latest_version: t.version,
            active_version: t.status === "active" ? t.version : null,
            versions: 1,
          });
        } else {
          cur.versions++;
          if (t.status === "active" && cur.active_version === null) cur.active_version = t.version;
        }
      }
      res.json([...byName.values()]);
    }),
  );

  // --- All versions for a template ---
  r.get(
    "/:name/versions",
    requireRole("read"),
    asyncHandler(async (req, res) => {
      const versions = await c.templates
        .find({ name: req.params.name! })
        .sort({ version: -1 })
        .toArray();
      res.json(versions.map(({ _id, ...v }) => v));
    }),
  );

  // --- Get one version (latest, or ?version=N) ---
  r.get(
    "/:name",
    requireRole("read"),
    asyncHandler(async (req, res) => {
      const version = req.query.version ? parseInt(String(req.query.version), 10) : undefined;
      const filter = version ? { name: req.params.name!, version } : { name: req.params.name! };
      const doc = await c.templates.find(filter).sort({ version: -1 }).limit(1).next();
      if (!doc) throw notFound("Template not found");
      const { _id, ...rest } = doc;
      res.json(rest);
    }),
  );

  // --- Create new draft version ---
  r.post(
    "/",
    requireRole("write"),
    asyncHandler(async (req, res) => {
      const { name, body } = parse(templateCreateSchema, req.body);
      lintTemplate(body);

      const latest = await c.templates.find({ name }).sort({ version: -1 }).limit(1).next();
      const version = (latest?.version ?? 0) + 1;
      const doc: TemplateDoc = {
        name,
        version,
        body,
        status: "draft",
        created_by: req.principal!.actor,
        created_at: new Date(),
      };
      await c.templates.insertOne(doc);
      await record(c, req.principal!, latest ? "template.update" : "template.create", name, {
        version,
      });
      const { _id, ...rest } = doc as TemplateDoc & { _id?: unknown };
      res.status(201).json(rest);
    }),
  );

  // --- Server-side validation (does not persist) ---
  r.post(
    "/:name/validate",
    requireRole("read"),
    asyncHandler(async (req, res) => {
      const body = typeof req.body?.body === "string" ? req.body.body : undefined;
      if (!body) throw badRequest("body (template text) required");
      lintTemplate(body);
      const result = validateTemplateBody(body);
      res.json(result);
    }),
  );

  // --- Activate a version (validate, then mark active; supersede others) ---
  r.post(
    "/:name/activate",
    requireRole("write"),
    asyncHandler(async (req, res) => {
      const version = req.body?.version
        ? parseInt(String(req.body.version), 10)
        : undefined;
      const doc = version
        ? await c.templates.findOne({ name: req.params.name!, version })
        : await c.templates.find({ name: req.params.name! }).sort({ version: -1 }).limit(1).next();
      if (!doc) throw notFound("Template version not found");

      // Validation failures block activation (PRD 9.3).
      const result = validateTemplateBody(doc.body);
      if (!result.ok) {
        res.status(400).json({ message: "Validation failed", ...result });
        return;
      }

      await c.templates.updateMany(
        { name: req.params.name!, status: "active" },
        { $set: { status: "draft" } },
      );
      await c.templates.updateOne(
        { name: req.params.name!, version: doc.version },
        { $set: { status: "active" } },
      );
      await record(c, req.principal!, "template.activate", req.params.name!, {
        version: doc.version,
      });
      res.json({ name: req.params.name!, version: doc.version, status: "active", ...result });
    }),
  );

  // --- Diff two versions (templates hold no secrets) ---
  r.get(
    "/:name/diff",
    requireRole("read"),
    asyncHandler(async (req, res) => {
      const from = parseInt(String(req.query.from), 10);
      const to = parseInt(String(req.query.to), 10);
      if (Number.isNaN(from) || Number.isNaN(to)) throw badRequest("from and to versions required");
      const a = await c.templates.findOne({ name: req.params.name!, version: from });
      const b = await c.templates.findOne({ name: req.params.name!, version: to });
      if (!a || !b) throw notFound("Version not found");
      res.json({ from: { version: from, body: a.body }, to: { version: to, body: b.body } });
    }),
  );

  return r;
}
