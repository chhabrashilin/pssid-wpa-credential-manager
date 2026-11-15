import { auth } from "express-openid-connect";
import type { RequestHandler } from "express";
import { createApp } from "./app.js";
import { loadConfig, loadKek } from "./config.js";
import { loadRoleMap } from "./auth/roles.js";
import { closeDb, connectDb } from "./db.js";
import { seedStarterTemplates } from "./services/seed.js";
import type { AppContext } from "./context.js";

async function main(): Promise<void> {
  const cfg = loadConfig();
  const kek = loadKek(); // throws if missing/invalid - fail fast
  const roleMap = loadRoleMap(cfg.roleMapFile);

  const c = await connectDb(cfg.mongoUrl, cfg.mongoDb);
  await seedStarterTemplates(c);

  const ctx: AppContext = { cfg, c, kek, roleMap };

  let oidcMiddleware: RequestHandler | undefined;
  if (cfg.ssoEnabled) {
    oidcMiddleware = auth({
      issuerBaseURL: cfg.oidc.issuerBaseUrl,
      baseURL: cfg.baseUrl,
      clientID: cfg.oidc.clientId,
      clientSecret: cfg.oidc.clientSecret,
      secret: cfg.oidc.sessionSecret,
      authRequired: false, // per-route guards enforce access
      idpLogout: true,
      authorizationParams: { response_type: "code", scope: "openid profile email groups" },
    });
  }

  const app = createApp(ctx, { oidcMiddleware });
  const server = app.listen(cfg.port, () => {
    console.log(`pSSID Credential Manager listening on :${cfg.port} (sso=${cfg.ssoEnabled}, openWrite=${cfg.openWrite})`);
  });

  const shutdown = async (sig: string) => {
    console.log(`${sig} received, shutting down`);
    server.close();
    await closeDb();
    process.exit(0);
  };
  process.on("SIGTERM", () => void shutdown("SIGTERM"));
  process.on("SIGINT", () => void shutdown("SIGINT"));
}

main().catch((err) => {
  console.error("Fatal startup error:", err instanceof Error ? err.message : err);
  process.exit(1);
});
