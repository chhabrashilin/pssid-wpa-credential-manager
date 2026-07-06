import fs from "node:fs";
import path from "node:path";
import express, { type Express } from "express";
import cookieParser from "cookie-parser";
import cors from "cors";
import helmet from "helmet";
import rateLimit from "express-rate-limit";
import type { AppContext } from "./context.js";
import {
  attachPrincipal,
  defaultUserResolver,
  type AuthResolver,
} from "./auth/middleware.js";
import { errorHandler, notFoundHandler } from "./util/errors.js";
import { healthRouter } from "./routes/health.js";
import { networksRouter } from "./routes/networks.js";
import { templatesRouter } from "./routes/templates.js";
import { bundlesRouter } from "./routes/bundles.js";
import { tokensRouter } from "./routes/tokens.js";
import { auditRouter } from "./routes/audit.js";
import { settingsRouter } from "./routes/settings.js";
import { dashboardRouter } from "./routes/dashboard.js";

export interface AppOptions {
  /** Override how the user principal is resolved (tests inject roles). */
  authResolver?: AuthResolver;
  /** Attach the express-openid-connect middleware (production SSO). */
  oidcMiddleware?: express.RequestHandler;
}

/**
 * Assemble the Express app. Auth is injectable so tests can exercise the
 * read/write/token/none authorization matrix without a live OIDC provider.
 */
export function createApp(ctx: AppContext, opts: AppOptions = {}): Express {
  const app = express();
  app.disable("x-powered-by");
  app.set("trust proxy", 1);

  app.use(helmet());
  app.use(cors({ origin: false }));
  app.use(cookieParser());
  app.use(express.json({ limit: "1mb" }));

  if (opts.oidcMiddleware) app.use(opts.oidcMiddleware);

  const resolver = opts.authResolver ?? defaultUserResolver(ctx.cfg, ctx.roleMap);

  // Health is open (no auth).
  app.use("/api/health", healthRouter(ctx));

  // Rate-limit the token-pull path (machine callers) and auth surface.
  const pullLimiter = rateLimit({ windowMs: 60_000, limit: 120, standardHeaders: true, legacyHeaders: false });

  const api = express.Router();
  api.use(attachPrincipal(resolver));

  // Identity of the current caller, so the UI can adapt to read/write role.
  api.get("/me", (req, res) => {
    const p = req.principal!;
    res.json({ actor: p.actor, role: p.role, sso_enabled: ctx.cfg.ssoEnabled });
  });

  api.use("/networks", networksRouter(ctx));
  api.use("/templates", templatesRouter(ctx));
  api.use("/bundles", pullLimiter, bundlesRouter(ctx));
  api.use("/tokens", tokensRouter(ctx));
  api.use("/audit", auditRouter(ctx));
  api.use("/settings", settingsRouter(ctx));
  api.use("/dashboard", dashboardRouter(ctx));
  app.use("/api/v1", api);

  // JSON 404 for any unknown API route (must precede the SPA fallback).
  app.use("/api", notFoundHandler);

  // Serve the built client (SPA) if present.
  const clientDist = process.env.CLIENT_DIST ?? path.resolve(process.cwd(), "../client/dist");
  if (fs.existsSync(clientDist)) {
    app.use(express.static(clientDist));
    app.get("*", (_req, res) => res.sendFile(path.join(clientDist, "index.html")));
  }

  app.use(errorHandler);
  return app;
}
