import { Router } from "express";
import type { AppContext } from "../context.js";
import type { BundleDoc, RenderDoc } from "../models/types.js";
import { requireRole } from "../auth/middleware.js";
import { requireToken } from "../auth/tokens.js";
import { seal, openString } from "../crypto/index.js";
import { record } from "../services/audit.js";
import { renderBundle } from "../services/render.js";
import { asyncHandler, badRequest, conflict, notFound } from "../util/errors.js";
import { bundleSchema, parse } from "../util/validate.js";

function bundleView(b: BundleDoc) {
  const { _id, ...rest } = b as BundleDoc & { _id?: unknown };
  return rest;
}

export function bundlesRouter(ctx: AppContext): Router {
  const r = Router();
  const { c, kek } = ctx;

  // --- List / get ---
  r.get(
    "/",
    requireRole("read"),
    asyncHandler(async (_req, res) => {
      const bundles = await c.bundles.find().sort({ name: 1 }).toArray();
      res.json(bundles.map(bundleView));
    }),
  );

  r.get(
    "/:name",
    requireRole("read"),
    asyncHandler(async (req, res) => {
      const b = await c.bundles.findOne({ name: req.params.name! });
      if (!b) throw notFound("Bundle not found");
      res.json(bundleView(b));
    }),
  );

  // --- Create / update / delete ---
  r.post(
    "/",
    requireRole("write"),
    asyncHandler(async (req, res) => {
      const input = parse(bundleSchema, req.body);
      if (await c.bundles.findOne({ name: input.name })) {
        throw conflict(`Bundle '${input.name}' already exists`);
      }
      const doc: BundleDoc = {
        ...input,
        render_version: 0,
        created_by: req.principal!.actor,
        updated_at: new Date(),
      };
      await c.bundles.insertOne(doc);
      await record(c, req.principal!, "bundle.create", input.name, {
        networks: input.network_names.length,
      });
      res.status(201).json(bundleView(doc));
    }),
  );

  r.put(
    "/:name",
    requireRole("write"),
    asyncHandler(async (req, res) => {
      const b = await c.bundles.findOne({ name: req.params.name! });
      if (!b) throw notFound("Bundle not found");
      const input = parse(bundleSchema.partial().omit({ name: true }), req.body);
      await c.bundles.updateOne(
        { name: req.params.name! },
        { $set: { ...input, updated_at: new Date() } },
      );
      await record(c, req.principal!, "bundle.update", req.params.name!, {});
      const updated = await c.bundles.findOne({ name: req.params.name! });
      res.json(bundleView(updated!));
    }),
  );

  r.delete(
    "/:name",
    requireRole("write"),
    asyncHandler(async (req, res) => {
      const b = await c.bundles.findOne({ name: req.params.name! });
      if (!b) throw notFound("Bundle not found");
      const token = await c.tokens.findOne({ scopes: req.params.name!, revoked_at: { $exists: false } });
      if (token) throw conflict(`Bundle is referenced by token '${token.name}'; revoke it first`);
      await c.bundles.deleteOne({ name: req.params.name! });
      await c.renders.deleteMany({ bundle_name: req.params.name! });
      await record(c, req.principal!, "bundle.delete", req.params.name!, {});
      res.status(204).end();
    }),
  );

  // --- Redacted preview (browser, PRD R7) ---
  r.get(
    "/:name/preview",
    requireRole("read"),
    asyncHandler(async (req, res) => {
      const { text } = await renderBundle(ctx, req.params.name!, /* redact */ true);
      res.type("text/plain").send(text);
    }),
  );

  // --- Produce + store a new render (write) ---
  r.post(
    "/:name/render",
    requireRole("write"),
    asyncHandler(async (req, res) => {
      const b = await c.bundles.findOne({ name: req.params.name! });
      if (!b) throw notFound("Bundle not found");

      // Real (unredacted) render, encrypted at rest — never written to disk clear.
      const { text, fingerprint } = await renderBundle(ctx, b.name, /* redact */ false);
      const version = b.render_version + 1;
      const sealed = seal(kek, text);
      const doc: RenderDoc = {
        bundle_name: b.name,
        version,
        fingerprint,
        rendered_by: req.principal!.actor,
        rendered_at: new Date(),
        ...sealed,
      };
      await c.renders.insertOne(doc);
      await c.bundles.updateOne({ name: b.name }, { $set: { render_version: version, updated_at: new Date() } });
      await record(c, req.principal!, "bundle.render", b.name, {
        render_version: version,
        fingerprint,
      });
      res.status(201).json({ bundle_name: b.name, version, fingerprint, rendered_at: doc.rendered_at });
    }),
  );

  // --- Render history (metadata only) ---
  r.get(
    "/:name/renders",
    requireRole("read"),
    asyncHandler(async (req, res) => {
      const renders = await c.renders
        .find({ bundle_name: req.params.name! }, { projection: { version: 1, fingerprint: 1, rendered_by: 1, rendered_at: 1 } })
        .sort({ version: -1 })
        .toArray();
      res.json(renders.map(({ _id, ...v }) => v));
    }),
  );

  // --- Diff two render versions (secrets redacted) ---
  r.get(
    "/:name/diff",
    requireRole("read"),
    asyncHandler(async (req, res) => {
      const from = parseInt(String(req.query.from), 10);
      const to = parseInt(String(req.query.to), 10);
      if (Number.isNaN(from) || Number.isNaN(to)) throw badRequest("from and to render versions required");
      const a = await c.renders.findOne({ bundle_name: req.params.name!, version: from });
      const b = await c.renders.findOne({ bundle_name: req.params.name!, version: to });
      if (!a || !b) throw notFound("Render version not found");
      res.json({
        from: { version: from, text: redactConf(openString(kek, a)) },
        to: { version: to, text: redactConf(openString(kek, b)) },
      });
    }),
  );

  // --- Machine pull (token-only): raw .conf with ETag/304 flow (PRD 9.5, R5) ---
  r.get(
    "/:name/render",
    requireToken(c),
    asyncHandler(async (req, res) => {
      const latest = await c.renders
        .find({ bundle_name: req.params.name! })
        .sort({ version: -1 })
        .limit(1)
        .next();
      if (!latest) throw notFound("No render available for this bundle");

      // Delivery hygiene (R5): never cache secret payloads.
      res.setHeader("Cache-Control", "no-store");
      res.setHeader("X-Render-Version", String(latest.version));
      res.setHeader("X-Render-Fingerprint", latest.fingerprint);
      res.setHeader("ETag", `"${latest.fingerprint}"`);

      const inm = req.header("if-none-match");
      if (inm && inm.replace(/"/g, "") === latest.fingerprint) {
        await record(c, req.principal!, "render.pull", req.params.name!, {
          render_version: latest.version,
          fingerprint: latest.fingerprint,
          result: "304",
        });
        res.status(304).end();
        return;
      }

      const text = openString(kek, latest);
      await record(c, req.principal!, "render.pull", req.params.name!, {
        render_version: latest.version,
        fingerprint: latest.fingerprint,
        result: "200",
      });
      res.type("text/plain").status(200).send(text);
    }),
  );

  return r;
}

/** Redact secret-looking values from stored render text for diff display. */
function redactConf(text: string): string {
  return text
    .replace(/(psk=)([0-9a-fA-F]{64})/g, "$1<redacted>")
    .replace(/(password=hash:)([0-9a-fA-F]{32})/g, "$1<redacted>")
    .replace(/(identity=")([^"]*)(")/g, '$1<redacted>$3');
}
