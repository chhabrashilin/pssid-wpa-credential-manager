import crypto from "node:crypto";

/**
 * Envelope encryption (PRD R1).
 *
 * Each secret gets a random 256-bit data key (DEK). The payload is encrypted
 * with AES-256-GCM under the DEK. The DEK is then wrapped (also AES-256-GCM)
 * under the master key (KEK). Rotating the KEK re-wraps DEKs without touching
 * the (potentially large / numerous) payloads.
 */

const ALG = "aes-256-gcm";
const IV_LEN = 12; // 96-bit nonce, recommended for GCM
const KEY_LEN = 32;

export interface SealedPayload {
  payload_ct: string; // base64 ciphertext
  payload_iv: string; // base64 iv
  payload_tag: string; // base64 auth tag
  dek_wrapped: string; // base64: iv(12) || tag(16) || wrappedKey(32)
}

function gcmEncrypt(key: Buffer, plaintext: Buffer): { ct: Buffer; iv: Buffer; tag: Buffer } {
  const iv = crypto.randomBytes(IV_LEN);
  const cipher = crypto.createCipheriv(ALG, key, iv);
  const ct = Buffer.concat([cipher.update(plaintext), cipher.final()]);
  const tag = cipher.getAuthTag();
  return { ct, iv, tag };
}

function gcmDecrypt(key: Buffer, ct: Buffer, iv: Buffer, tag: Buffer): Buffer {
  const decipher = crypto.createDecipheriv(ALG, key, iv);
  decipher.setAuthTag(tag);
  return Buffer.concat([decipher.update(ct), decipher.final()]);
}

/** Wrap a DEK under the KEK. Returns iv(12) || tag(16) || ciphertext(32). */
function wrapDek(kek: Buffer, dek: Buffer): Buffer {
  const { ct, iv, tag } = gcmEncrypt(kek, dek);
  return Buffer.concat([iv, tag, ct]);
}

function unwrapDek(kek: Buffer, wrapped: Buffer): Buffer {
  const iv = wrapped.subarray(0, IV_LEN);
  const tag = wrapped.subarray(IV_LEN, IV_LEN + 16);
  const ct = wrapped.subarray(IV_LEN + 16);
  return gcmDecrypt(kek, ct, iv, tag);
}

/** Encrypt a UTF-8 secret string with a fresh DEK, wrapping the DEK under kek. */
export function seal(kek: Buffer, plaintext: string | Buffer): SealedPayload {
  const dek = crypto.randomBytes(KEY_LEN);
  const buf = typeof plaintext === "string" ? Buffer.from(plaintext, "utf8") : plaintext;
  const { ct, iv, tag } = gcmEncrypt(dek, buf);
  const wrapped = wrapDek(kek, dek);
  return {
    payload_ct: ct.toString("base64"),
    payload_iv: iv.toString("base64"),
    payload_tag: tag.toString("base64"),
    dek_wrapped: wrapped.toString("base64"),
  };
}

/** Decrypt a sealed payload back to a Buffer. */
export function open(kek: Buffer, sealed: SealedPayload): Buffer {
  const wrapped = Buffer.from(sealed.dek_wrapped, "base64");
  const dek = unwrapDek(kek, wrapped);
  return gcmDecrypt(
    dek,
    Buffer.from(sealed.payload_ct, "base64"),
    Buffer.from(sealed.payload_iv, "base64"),
    Buffer.from(sealed.payload_tag, "base64"),
  );
}

/** Decrypt a sealed payload to a UTF-8 string. */
export function openString(kek: Buffer, sealed: SealedPayload): string {
  return open(kek, sealed).toString("utf8");
}

/**
 * Re-wrap a DEK from an old KEK to a new one WITHOUT decrypting the payload
 * (PRD R1: KEK rotation re-wraps data keys only). Returns the new dek_wrapped.
 */
export function rewrapDek(oldKek: Buffer, newKek: Buffer, dekWrapped: string): string {
  const dek = unwrapDek(oldKek, Buffer.from(dekWrapped, "base64"));
  const rewrapped = wrapDek(newKek, dek);
  return rewrapped.toString("base64");
}
