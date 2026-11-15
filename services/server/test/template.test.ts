import { describe, expect, it } from "vitest";
import {
  lintTemplate,
  renderTemplate,
  validateTemplateBody,
  validateWpaSupplicant,
  type TemplateContext,
} from "../src/services/template.js";
import { STARTER_TEMPLATES } from "../src/services/seed.js";

const peapCtx: TemplateContext = {
  ssid: "MWireless",
  name: "mwireless",
  security: "wpa-eap-peap-mschapv2",
  priority: 5,
  scan_ssid: 0,
  identity: "pssid-probe",
  password_nthash: "8846f7eaee8fb117ad06bdd830b7586c",
  ca_cert: "/etc/ssl/certs/umich.pem",
};

describe("template rendering - starter templates", () => {
  it("renders peap-mschapv2 with the hash: form and no clear text", () => {
    const out = renderTemplate(STARTER_TEMPLATES["peap-mschapv2"]!, peapCtx);
    expect(out).toContain('identity="pssid-probe"');
    expect(out).toContain("password=hash:8846f7eaee8fb117ad06bdd830b7586c");
    expect(out).toContain('ca_cert="/etc/ssl/certs/umich.pem"');
    expect(out).not.toMatch(/password=(?!hash:)/); // never a bare clear password
  });

  it("renders wpa-psk with a 64-hex psk", () => {
    const out = renderTemplate(STARTER_TEMPLATES["wpa-psk"]!, {
      ssid: "guest",
      name: "guest",
      security: "wpa-psk",
      priority: 1,
      scan_ssid: 0,
      psk_hex: "a".repeat(64),
    });
    expect(out).toContain("psk=" + "a".repeat(64));
    expect(out).toContain("key_mgmt=WPA-PSK");
  });

  it("omits ca_cert line when ca_cert is undefined", () => {
    const out = renderTemplate(STARTER_TEMPLATES["peap-mschapv2"]!, { ...peapCtx, ca_cert: undefined });
    expect(out).not.toContain("ca_cert=");
  });
});

describe("template sandbox - fail closed", () => {
  it("throws on undefined variables", () => {
    expect(() => renderTemplate("psk={{ missing_var }}", { ssid: "x", name: "x", security: "wpa-psk", priority: 0, scan_ssid: 0 })).toThrow();
  });

  it.each([
    "{{ ''.constructor }}",
    "{{ ''.__proto__ }}",
    "{% include 'secret.conf' %}",
    "{% import 'x' as y %}",
    "{% extends 'base' %}",
    "{{ process.env }}",
    "{{ global }}",
  ])("rejects sandbox-escape construct: %s", (body) => {
    expect(() => lintTemplate(body)).toThrow();
  });

  it("allows the legitimate {% if %} used by starter templates", () => {
    expect(() => lintTemplate(STARTER_TEMPLATES["peap-mschapv2"]!)).not.toThrow();
  });
});

describe("wpa_supplicant output validation", () => {
  it("accepts a well-formed block", () => {
    const r = validateWpaSupplicant(`network={\n  ssid="x"\n  key_mgmt=WPA-PSK\n  psk=${"a".repeat(64)}\n}`);
    expect(r.ok).toBe(true);
    expect(r.errors).toHaveLength(0);
  });

  it("flags an unbalanced block as an error", () => {
    const r = validateWpaSupplicant(`network={\n  ssid="x"`);
    expect(r.ok).toBe(false);
  });

  it("warns (not errors) on an unknown key", () => {
    const r = validateWpaSupplicant(`network={\n  ssidd="x"\n}`);
    expect(r.ok).toBe(true);
    expect(r.warnings.join(" ")).toMatch(/unknown network key 'ssidd'/);
  });

  it("validateTemplateBody passes for both starter templates", () => {
    expect(validateTemplateBody(STARTER_TEMPLATES["wpa-psk"]!).ok).toBe(true);
    expect(validateTemplateBody(STARTER_TEMPLATES["peap-mschapv2"]!).ok).toBe(true);
  });
});
