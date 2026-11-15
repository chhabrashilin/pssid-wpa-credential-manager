import fs from "node:fs";

/**
 * Application configuration, resolved once at startup from the environment.
 * Fails fast (throws) on invalid crypto / auth configuration so the process
 * never comes up in an insecure half-state.
 */
export interface AppConfig {
  port: number;
  nodeEnv: string;
  baseUrl: string;
  mongoUrl: string;
  mongoDb: string;
  ssoEnabled: boolean;
  openWrite: boolean;
  oidc: {
    issuerBaseUrl: string;
    clientId: string;
    clientSecret: string;
    sessionSecret: string;
  };
  roleMapFile: string;
  rotationWarnDays: number;
}

function bool(v: string | undefined, dflt = false): boolean {
  if (v === undefined) return dflt;
  return ["1", "true", "yes", "on"].includes(v.toLowerCase());
}

/**
 * Load the 32-byte master key (KEK). Preference order:
 *   1. KEK_FILE  - a file readable only by the app (installer writes mode 0400)
 *   2. KEK_BASE64 - base64 of 32 raw bytes (container platforms)
 * Throws if neither resolves to exactly 32 bytes.
 */
export function loadKek(env: NodeJS.ProcessEnv = process.env): Buffer {
  const file = env.KEK_FILE;
  const b64 = env.KEK_BASE64;

  let key: Buffer | undefined;
  if (file && fs.existsSync(file)) {
    const raw = fs.readFileSync(file);
    // Accept either 32 raw bytes or a base64/hex text file.
    if (raw.length === 32) {
      key = raw;
    } else {
      const text = raw.toString("utf8").trim();
      key = decodeKeyText(text);
    }
  } else if (b64) {
    key = decodeKeyText(b64.trim());
  }

  if (!key) {
    throw new Error(
      "No master key found. Set KEK_FILE to a readable key file or KEK_BASE64.",
    );
  }
  if (key.length !== 32) {
    throw new Error(
      `Master key must be exactly 32 bytes (got ${key.length}). Generate with: make genkey`,
    );
  }
  return key;
}

function decodeKeyText(text: string): Buffer | undefined {
  // Try base64 first, then hex.
  const b64 = Buffer.from(text, "base64");
  if (b64.length === 32) return b64;
  if (/^[0-9a-fA-F]{64}$/.test(text)) return Buffer.from(text, "hex");
  return undefined;
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): AppConfig {
  const ssoEnabled = bool(env.SSO_ENABLED, false);
  const cfg: AppConfig = {
    port: parseInt(env.PORT ?? "8080", 10),
    nodeEnv: env.NODE_ENV ?? "development",
    baseUrl: env.BASE_URL ?? "http://localhost:8080",
    mongoUrl: env.MONGO_URL ?? "mongodb://localhost:27017",
    mongoDb: env.MONGO_DB ?? "credmgr",
    ssoEnabled,
    openWrite: bool(env.OPEN_WRITE, false),
    oidc: {
      issuerBaseUrl: env.OIDC_ISSUER_BASE_URL ?? "",
      clientId: env.OIDC_CLIENT_ID ?? "",
      clientSecret: env.OIDC_CLIENT_SECRET ?? "",
      sessionSecret: env.SESSION_SECRET ?? "",
    },
    roleMapFile: env.ROLE_MAP_FILE ?? "",
    rotationWarnDays: parseInt(env.ROTATION_WARN_DAYS ?? "180", 10),
  };

  if (ssoEnabled) {
    const { issuerBaseUrl, clientId, clientSecret, sessionSecret } = cfg.oidc;
    if (!issuerBaseUrl || !clientId || !clientSecret || !sessionSecret) {
      throw new Error(
        "SSO_ENABLED=true requires OIDC_ISSUER_BASE_URL, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET, SESSION_SECRET.",
      );
    }
  }
  return cfg;
}
