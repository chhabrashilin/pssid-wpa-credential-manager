import crypto from "node:crypto";
import { md4 } from "./md4.js";

/**
 * Derived, non-clear-text credential forms (PRD R3).
 *
 * These functions turn a human secret into the form wpa_supplicant accepts
 * directly, so the rendered .conf never contains the human passphrase/password.
 * The derived forms are still network-equivalent secrets (PRD R4) - they are
 * not "safe to share".
 */

/**
 * WPA-PSK derived key: PBKDF2-SHA1(passphrase, ssid, 4096, 32) as 64 hex chars.
 * Byte-for-byte identical to what `wpa_passphrase <ssid> <passphrase>` emits.
 */
export function derivePskHex(passphrase: string, ssid: string): string {
  const key = crypto.pbkdf2Sync(
    Buffer.from(passphrase, "utf8"),
    Buffer.from(ssid, "utf8"),
    4096,
    32,
    "sha1",
  );
  return key.toString("hex");
}

/** True if the value is already a raw 64-hex PSK (accept as pre-derived). */
export function isRawPskHex(value: string): boolean {
  return /^[0-9a-fA-F]{64}$/.test(value.trim());
}

/**
 * NT hash (MSCHAPv2): MD4 of the UTF-16LE-encoded password, as 32 lowercase
 * hex chars. wpa_supplicant accepts this as `password=hash:<32-hex>`.
 */
export function deriveNtHash(password: string): string {
  const utf16le = Buffer.from(password, "utf16le");
  return md4(utf16le).toString("hex");
}
