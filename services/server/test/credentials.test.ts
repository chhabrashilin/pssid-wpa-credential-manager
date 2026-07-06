import crypto from "node:crypto";
import { describe, expect, it } from "vitest";
import { buildSealedCredential, openCredential } from "../src/services/credentials.js";
import { deriveForms, buildContext } from "../src/services/render.js";
import { derivePskHex, deriveNtHash } from "../src/crypto/derive.js";
import type { AppContext } from "../src/context.js";
import type { CredentialDoc, NetworkDoc } from "../src/models/types.js";

const kek = crypto.randomBytes(32);
const ctx = { kek } as AppContext;

function credDoc(frag: ReturnType<typeof buildSealedCredential>): CredentialDoc {
  return {
    network_name: "n",
    version: 1,
    status: "active",
    created_by: "test",
    created_at: new Date(),
    ...frag,
  };
}

const net = (over: Partial<NetworkDoc> = {}): NetworkDoc => ({
  name: "mwireless",
  ssid: "MWireless",
  security: "wpa-eap-peap-mschapv2",
  priority: 5,
  scan_ssid: 0,
  template_name: "peap-mschapv2",
  variables: {},
  credential_version: 1,
  created_by: "t",
  created_at: new Date(),
  updated_at: new Date(),
  ...over,
});

describe("credential seal → open round-trip", () => {
  it("psk: stores passphrase encrypted, derives correct psk_hex", () => {
    const frag = buildSealedCredential(kek, "psk", { passphrase: "password" });
    const payload = openCredential(kek, credDoc(frag));
    expect(payload.passphrase).toBe("password");

    const forms = deriveForms(ctx, net({ ssid: "IEEE", security: "wpa-psk" }), credDoc(frag));
    expect(forms.psk_hex).toBe(derivePskHex("password", "IEEE"));
  });

  it("psk: accepts a raw 64-hex key as pre-derived", () => {
    const raw = "a".repeat(64);
    const frag = buildSealedCredential(kek, "psk", { passphrase: raw });
    const forms = deriveForms(ctx, net({ security: "wpa-psk" }), credDoc(frag));
    expect(forms.psk_hex).toBe(raw);
  });

  it("peap: derives NT hash, never exposes clear password", () => {
    const frag = buildSealedCredential(kek, "peap-mschapv2", {
      identity: "pssid-probe",
      password: "password",
    });
    const forms = deriveForms(ctx, net(), credDoc(frag));
    expect(forms.identity).toBe("pssid-probe");
    expect(forms.password_nthash).toBe(deriveNtHash("password"));
    expect(forms.password_nthash).toBe("8846f7eaee8fb117ad06bdd830b7586c");
  });

  it("fingerprint is stable and 8 hex", () => {
    const frag = buildSealedCredential(kek, "psk", { passphrase: "password" });
    expect(frag.fingerprint).toMatch(/^[0-9a-f]{8}$/);
  });
});

describe("credential write-time validation", () => {
  it("rejects a too-short PSK passphrase", () => {
    expect(() => buildSealedCredential(kek, "psk", { passphrase: "short" })).toThrow();
  });
  it("rejects a non-PEM EAP-TLS private key", () => {
    expect(() =>
      buildSealedCredential(kek, "eap-tls", { client_cert: "x", private_key: "not-a-key" }),
    ).toThrow();
  });
  it("accepts a PEM-looking private key", () => {
    expect(() =>
      buildSealedCredential(kek, "eap-tls", {
        client_cert: "CERT",
        private_key: "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----",
      }),
    ).not.toThrow();
  });
});

describe("preview redaction (PRD R7)", () => {
  it("replaces secret-derived values with redacted fingerprint placeholders", () => {
    const frag = buildSealedCredential(kek, "peap-mschapv2", {
      identity: "pssid-probe",
      password: "password",
    });
    const forms = deriveForms(ctx, net(), credDoc(frag));
    const redacted = buildContext(net(), forms, /* redact */ true);
    expect(redacted.password_nthash).toMatch(/^<redacted:fp [0-9a-f]{8}>$/);
    expect(redacted.identity).toMatch(/^<redacted:fp/);
    expect(redacted.password_nthash).not.toContain("8846f7");
  });
});
