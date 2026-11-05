import { Router } from "express";
import type { AppContext } from "../context.js";
import type { NetworkDoc } from "../models/types.js";
import { requireRole } from "../auth/middleware.js";
import { record } from "../services/audit.js";
import {
  buildSealedCredential,
  credentialTypeFor,
  setCredentialVersion,
} from "../services/credentials.js";
import { asyncHandler, badRequest, conflict, notFound } from "../util/errors.js";
import { networkCreateSchema, networkUpdateSchema, parse } from "../util/validate.js";

/** Public (secret-free) view of a network, enriched with credential metadata. */
async function toView(ctx: AppContext, n: NetworkDoc) {
  const cred = await ctx.c.credentials.findOne(
    { network_name: n.name, status: "active" },
    { projection: { fingerprint: 1, version: 1, created_at: 1 } },
  );
  const template = await ctx.c.templates.findOne(
    { name: n.template_name, status: "active" },
    { projection: { version: 1 } },
  );
  return {
    name: n.name,
    ssid: n.ssid,
    security: n.security,
    priority: n.priority,
    scan_ssid: n.scan_ssid,
    notes: n.notes ?? "",
    template_name: n.template_name,
    template_version: template?.version ?? null,
    variables: n.variables,
    credential: cred
      ? { fingerprint: cred.fingerprint, version: cred.version, created_at: cred.created_at }
      : null,
    created_by: n.created_by,
    created_at: n.created_at,
    updated_at: n.updated_at,
  };
}

export function networksRouter(ctx: AppContext): Router {
  const r = Router();
  const { c, kek } = ctx;

  // --- List ---
  r.get(
    "/",
    requireRole("read"),
    asyncHandler(async (_req, res) => {
      const nets = await c.networks.find().sort({ name: 1 }).toArray();
      res.json(await Promise.all(nets.map((n) => toView(ctx, n))));
    }),
  );

  // --- Get one ---
  r.get(
    "/:name",
    requireRole("read"),
    asyncHandler(async (req, res) => {
      const n = await c.networks.findOne({ name: req.params.name! });
      if (!n) throw notFound("Network not found");
      res.json(await toView(ctx, n));
    }),
  );

  // --- Create ---
  r.post(
    "/",
    requireRole("write"),
    asyncHandler(async (req, res) => {
      const input = parse(networkCreateSchema, req.body);
      const existing = await c.networks.findOne({ name: input.name });
      if (existing) throw conflict(`Network '${input.name}' already exists`);

      const now = new Date();
      const doc: NetworkDoc = {
        ...input,
        credential_version: 0,
        created_by: req.principal!.actor,
        created_at: now,
        updated_at: now,
      };
      await c.networks.insertOne(doc);
      await record(c, req.principal!, "network.create", input.name, {
        security: input.security,
      });
      res.status(201).json(await toView(ctx, doc));
    }),
  );

  // --- Update (never touches credentials) ---
  r.put(
    "/:name",
    requireRole("write"),
    asyncHandler(async (req, res) => {
      const patch = parse(networkUpdateSchema, req.body);
      const n = await c.networks.findOne({ name: req.params.name! });
      if (!n) throw notFound("Network not found");

      await c.networks.updateOne(
        { name: req.params.name! },
        { $set: { ...patch, updated_at: new Date() } },
      );
      await record(c, req.principal!, "network.update", req.params.name!, {});
      const updated = await c.networks.findOne({ name: req.params.name! });
      res.json(await toView(ctx, updated!));
    }),
  );

  // --- Delete (blocked if referenced by a bundle) ---
  r.delete(
    "/:name",
    requireRole("write"),
    asyncHandler(async (req, res) => {
      const n = await c.networks.findOne({ name: req.params.name! });
      if (!n) throw notFound("Network not found");
      const inBundle = await c.bundles.findOne({ network_names: req.params.name! });
      if (inBundle) throw conflict(`Network is used by bundle '${inBundle.name}'`);

      await c.networks.deleteOne({ name: req.params.name! });
      await c.credentials.deleteMany({ network_name: req.params.name! });
      await record(c, req.principal!, "network.delete", req.params.name!, {});
      res.status(204).end();
    }),
  );

  // --- Set / rotate credential (write-only, PRD R2) ---
  r.put(
    "/:name/credential",
    requireRole("write"),
    asyncHandler(async (req, res) => {
      const n = await c.networks.findOne({ name: req.params.name! });
      if (!n) throw notFound("Network not found");
      const type = credentialTypeFor(n.security);
      if (!type) throw badRequest("Open networks have no credential");

      const fragment = buildSealedCredential(kek, type, req.body);
      const rotating = n.credential_version > 0;
      const doc = await setCredentialVersion(c, n.name, fragment, req.principal!.actor);

      await record(
        c,
        req.principal!,
        rotating ? "credential.rotate" : "credential.set",
        n.name,
        { version: doc.version, fingerprint: doc.fingerprint },
      );
      // Response carries metadata ONLY - never the value (PRD R2).
      res.status(201).json({
        network_name: n.name,
        version: doc.version,
        fingerprint: doc.fingerprint,
        type: doc.type,
        created_at: doc.created_at,
      });
    }),
  );

  // --- Rollback to an older version (re-activate) ---
  r.post(
    "/:name/credential/rollback/:version",
    requireRole("write"),
    asyncHandler(async (req, res) => {
      const n = await c.networks.findOne({ name: req.params.name! });
      if (!n) throw notFound("Network not found");
      const version = parseInt(req.params.version!, 10);
      const target = await c.credentials.findOne({ network_name: n.name, version });
      if (!target) throw notFound("Credential version not found");

      // Create a NEW version that is a copy of the target's sealed material, so
      // history stays append-only and the render version bumps.
      const doc = await setCredentialVersion(
        c,
        n.name,
        {
          type: target.type,
          fingerprint: target.fingerprint,
          payload_ct: target.payload_ct,
          payload_iv: target.payload_iv,
          payload_tag: target.payload_tag,
          dek_wrapped: target.dek_wrapped,
        },
        req.principal!.actor,
      );
      await record(c, req.principal!, "credential.rollback", n.name, {
        version: doc.version,
        fingerprint: doc.fingerprint,
        rolled_back_from: version,
      });
      res.status(201).json({
        network_name: n.name,
        version: doc.version,
        fingerprint: doc.fingerprint,
        restored_from_version: version,
      });
    }),
  );

  // --- Credential version history (metadata only) ---
  r.get(
    "/:name/credential/versions",
    requireRole("read"),
    asyncHandler(async (req, res) => {
      const versions = await c.credentials
        .find(
          { network_name: req.params.name! },
          { projection: { fingerprint: 1, version: 1, status: 1, created_by: 1, created_at: 1, type: 1 } },
        )
        .sort({ version: -1 })
        .toArray();
      res.json(versions.map(({ _id, ...v }) => v));
    }),
  );

  return r;
}
