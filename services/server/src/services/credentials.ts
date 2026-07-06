import { z } from "zod";
import type { Collections } from "../db.js";
import type { CredentialDoc, CredentialType, SecurityType } from "../models/types.js";
import { fingerprint, open, seal } from "../crypto/index.js";
import { badRequest } from "../util/errors.js";
import { parse } from "../util/validate.js";

/**
 * Maps a network security type to the credential type it stores.
 * `open` networks carry no credential.
 */
export function credentialTypeFor(security: SecurityType): CredentialType | null {
  switch (security) {
    case "wpa-psk":
      return "psk";
    case "wpa-eap-peap-mschapv2":
      return "peap-mschapv2";
    case "eap-tls":
      return "eap-tls";
    case "open":
      return null;
  }
}

// --- Write-time validation (PRD 9.2) ---

const pskSchema = z.object({
  // 8-63 printable ASCII passphrase, OR an already-derived 64-hex raw PSK.
  passphrase: z
    .string()
    .refine(
      (s) => /^[0-9a-fA-F]{64}$/.test(s) || (/^[\x20-\x7e]{8,63}$/.test(s)),
      "PSK must be an 8-63 char printable-ASCII passphrase or a 64-hex raw key",
    ),
});

const peapSchema = z.object({
  identity: z.string().min(1, "identity required").max(255),
  password: z.string().min(1, "password required").max(255),
});

const eapTlsSchema = z.object({
  client_cert: z.string().min(1, "client_cert (PEM) required"),
  private_key: z
    .string()
    .refine((s) => /-----BEGIN [A-Z ]*PRIVATE KEY-----/.test(s), "private_key must be PEM"),
  ca_cert: z.string().optional(),
});

/** The canonical raw secret material we fingerprint (never stored in clear). */
function primarySecret(type: CredentialType, payload: Record<string, string>): string {
  switch (type) {
    case "psk":
      return payload.passphrase!;
    case "peap-mschapv2":
      return payload.password!;
    case "eap-tls":
      return payload.private_key!;
  }
}

/**
 * Validate + seal a credential submission into an (unversioned) doc fragment.
 * The payload is serialized as JSON and envelope-encrypted; the fingerprint is
 * computed over the primary raw secret.
 */
export function buildSealedCredential(
  kek: Buffer,
  type: CredentialType,
  input: unknown,
): Pick<CredentialDoc, "type" | "fingerprint" | "payload_ct" | "payload_iv" | "payload_tag" | "dek_wrapped"> {
  let payload: Record<string, string>;
  switch (type) {
    case "psk":
      payload = parse(pskSchema, input);
      break;
    case "peap-mschapv2":
      payload = parse(peapSchema, input);
      break;
    case "eap-tls":
      payload = parse(eapTlsSchema, input);
      break;
    default:
      throw badRequest("Unsupported credential type");
  }

  const sealed = seal(kek, JSON.stringify(payload));
  return {
    type,
    fingerprint: fingerprint(primarySecret(type, payload)),
    ...sealed,
  };
}

/** Decrypt a stored credential back to its raw payload (server-side only). */
export function openCredential(kek: Buffer, doc: CredentialDoc): Record<string, string> {
  const json = open(kek, doc).toString("utf8");
  return JSON.parse(json) as Record<string, string>;
}

/**
 * Insert a new credential version for a network, superseding the current
 * active one, and bump the network's credential_version. Returns the new doc.
 */
export async function setCredentialVersion(
  c: Collections,
  networkName: string,
  fragment: ReturnType<typeof buildSealedCredential>,
  createdBy: string,
): Promise<CredentialDoc> {
  const latest = await c.credentials
    .find({ network_name: networkName })
    .sort({ version: -1 })
    .limit(1)
    .next();
  const version = (latest?.version ?? 0) + 1;

  await c.credentials.updateMany(
    { network_name: networkName, status: "active" },
    { $set: { status: "superseded" } },
  );

  const doc: CredentialDoc = {
    network_name: networkName,
    version,
    status: "active",
    created_by: createdBy,
    created_at: new Date(),
    ...fragment,
  };
  await c.credentials.insertOne(doc);
  await c.networks.updateOne(
    { name: networkName },
    { $set: { credential_version: version, updated_at: new Date() } },
  );
  return doc;
}
