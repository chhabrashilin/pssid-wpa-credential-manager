import { describe, expect, it } from "vitest";
import { deriveNtHash, derivePskHex, isRawPskHex } from "../src/crypto/derive.js";

// IEEE 802.11i / RFC-standard WPA-PSK PBKDF2 test vectors - these are exactly
// what `wpa_passphrase <ssid> <passphrase>` emits.
describe("derivePskHex (wpa_passphrase vectors)", () => {
  it.each([
    ["password", "IEEE", "f42c6fc52df0ebef9ebb4b90b38a5f902e83fe1b135a70e23aed762e9710a12e"],
    ["ThisIsAPassword", "ThisIsASSID", "0dc0d6eb90555ed6419756b9a15ec3e3209b63df707dd508d14581f8982721af"],
    [
      "a".repeat(63),
      "Z".repeat(32),
      "2d43d0dabfdd635377172efa1fc4b4b87dbfc4219193909ded9a7cfb89a3097b",
    ],
  ])("PSK(%j, %j)", (passphrase, ssid, expected) => {
    expect(derivePskHex(passphrase, ssid)).toBe(expected);
  });

  it("produces 64 hex chars", () => {
    expect(derivePskHex("hunter2000", "mwireless")).toMatch(/^[0-9a-f]{64}$/);
  });
});

describe("isRawPskHex", () => {
  it("accepts 64 hex", () => expect(isRawPskHex("a".repeat(64))).toBe(true));
  it("rejects short/non-hex", () => {
    expect(isRawPskHex("abc")).toBe(false);
    expect(isRawPskHex("z".repeat(64))).toBe(false);
  });
});

// NT hash = MD4(UTF-16LE(password)). "password" → the value in the PRD example.
describe("deriveNtHash (MSCHAPv2 NT hash vectors)", () => {
  it.each([
    ["password", "8846f7eaee8fb117ad06bdd830b7586c"],
    ["", "31d6cfe0d16ae931b73c59d7e0c089c0"],
    ["welcome", "674e48b68c5cd0efd8f7e5faa87b3d1e"],
  ])("NT(%j)", (pw, expected) => {
    expect(deriveNtHash(pw)).toBe(expected);
  });

  it("produces 32 hex chars", () => {
    expect(deriveNtHash("MyPassw0rd!")).toMatch(/^[0-9a-f]{32}$/);
  });
});
