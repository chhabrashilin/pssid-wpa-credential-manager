import crypto from "node:crypto";
import { describe, expect, it } from "vitest";
import { open, openString, rewrapDek, seal } from "../src/crypto/envelope.js";
import { fingerprint } from "../src/crypto/fingerprint.js";

const KEK = () => crypto.randomBytes(32);

describe("envelope encryption round-trip", () => {
  it("seals and opens a UTF-8 secret", () => {
    const kek = KEK();
    const sealed = seal(kek, "correct horse battery staple");
    expect(openString(kek, sealed)).toBe("correct horse battery staple");
  });

  it("produces distinct ciphertext for identical plaintext (random DEK+IV)", () => {
    const kek = KEK();
    const a = seal(kek, "same");
    const b = seal(kek, "same");
    expect(a.payload_ct).not.toBe(b.payload_ct);
    expect(a.dek_wrapped).not.toBe(b.dek_wrapped);
  });

  it("fails to open with the wrong KEK (GCM auth)", () => {
    const sealed = seal(KEK(), "secret");
    expect(() => open(KEK(), sealed)).toThrow();
  });

  it("fails to open when ciphertext is tampered", () => {
    const kek = KEK();
    const sealed = seal(kek, "secret");
    const bytes = Buffer.from(sealed.payload_ct, "base64");
    bytes[0] ^= 0xff;
    expect(() => open(kek, { ...sealed, payload_ct: bytes.toString("base64") })).toThrow();
  });

  it("handles binary payloads (e.g. PEM key bytes)", () => {
    const kek = KEK();
    const buf = crypto.randomBytes(2048);
    const sealed = seal(kek, buf);
    expect(open(kek, sealed).equals(buf)).toBe(true);
  });
});

describe("KEK rotation (re-wrap without re-encrypting payload)", () => {
  it("re-wraps the DEK under a new KEK and still decrypts", () => {
    const oldKek = KEK();
    const newKek = KEK();
    const sealed = seal(oldKek, "rotate-me");

    const rewrapped = { ...sealed, dek_wrapped: rewrapDek(oldKek, newKek, sealed.dek_wrapped) };

    // Payload ciphertext is unchanged - only the wrapped key changed.
    expect(rewrapped.payload_ct).toBe(sealed.payload_ct);
    expect(rewrapped.dek_wrapped).not.toBe(sealed.dek_wrapped);

    // New KEK opens it; old KEK no longer does.
    expect(openString(newKek, rewrapped)).toBe("rotate-me");
    expect(() => open(oldKek, rewrapped)).toThrow();
  });
});

describe("fingerprint", () => {
  it("is 8 hex chars and stable", () => {
    expect(fingerprint("password")).toMatch(/^[0-9a-f]{8}$/);
    expect(fingerprint("password")).toBe(fingerprint("password"));
    expect(fingerprint("password")).not.toBe(fingerprint("password2"));
  });
});
