import type { Collections } from "../db.js";
import type { TemplateDoc } from "../models/types.js";

/** Starter templates shipped with the product (PRD Section 13). */
export const STARTER_TEMPLATES: Record<string, string> = {
  "wpa-psk": `network={
    ssid="{{ ssid }}"
    scan_ssid={{ scan_ssid }}
    key_mgmt=WPA-PSK
    psk={{ psk_hex }}
    priority={{ priority }}
}
`,
  "peap-mschapv2": `network={
    ssid="{{ ssid }}"
    scan_ssid={{ scan_ssid }}
    key_mgmt=WPA-EAP
    eap=PEAP
    identity="{{ identity }}"
    password=hash:{{ password_nthash }}
    phase2="auth=MSCHAPV2"
    {% if ca_cert %}ca_cert="{{ ca_cert }}"{% endif %}
    priority={{ priority }}
}
`,
};

/**
 * Seed the two starter templates as active v1 if they don't already exist.
 * Idempotent - safe to call on every startup.
 */
export async function seedStarterTemplates(c: Collections): Promise<void> {
  for (const [name, body] of Object.entries(STARTER_TEMPLATES)) {
    const exists = await c.templates.findOne({ name });
    if (exists) continue;
    const doc: TemplateDoc = {
      name,
      version: 1,
      body,
      status: "active",
      created_by: "system",
      created_at: new Date(),
    };
    await c.templates.insertOne(doc);
  }
}
