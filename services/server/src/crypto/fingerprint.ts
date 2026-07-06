import crypto from "node:crypto";

/**
 * Non-reversible fingerprint of secret material: first 8 hex chars of the
 * SHA-256 of the raw value (PRD R2). Used everywhere a human needs to confirm
 * "which secret is this" without ever seeing the value.
 */
export function fingerprint(raw: string | Buffer): string {
  const buf = typeof raw === "string" ? Buffer.from(raw, "utf8") : raw;
  return crypto.createHash("sha256").update(buf).digest("hex").slice(0, 8);
}

/** SHA-256 hex of a token value (tokens are stored hashed, never in clear). */
export function tokenHash(token: string): string {
  return crypto.createHash("sha256").update(token, "utf8").digest("hex");
}

/** Generate a cryptographically random opaque token value (shown once). */
export function generateToken(): string {
  return "credmgr_" + crypto.randomBytes(32).toString("base64url");
}
