import type { AppContext } from "../context.js";
import type { CredentialDoc, NetworkDoc } from "../models/types.js";
import { deriveNtHash, derivePskHex, fingerprint, isRawPskHex } from "../crypto/index.js";
import { badRequest, notFound } from "../util/errors.js";
import { openCredential } from "./credentials.js";
import { renderTemplate, type TemplateContext } from "./template.js";

/** Secret-derived context keys that must be redacted in preview mode (PRD R7). */
const SECRET_KEYS = ["psk_hex", "password_nthash", "identity", "private_key", "client_cert"] as const;

interface DerivedForms {
  psk_hex?: string;
  identity?: string;
  password_nthash?: string;
  client_cert?: string;
  private_key?: string;
  ca_cert?: string;
  fingerprint: string | null;
}

/**
 * Turn a network's active credential into the derived, non-clear-text forms
 * the templates consume (PRD R3). The human passphrase/password never appears.
 */
export function deriveForms(ctx: AppContext, network: NetworkDoc, cred: CredentialDoc | null): DerivedForms {
  if (!cred) return { fingerprint: null };
  const payload = openCredential(ctx.kek, cred);

  switch (cred.type) {
    case "psk": {
      const passphrase = payload.passphrase!;
      const psk_hex = isRawPskHex(passphrase)
        ? passphrase.toLowerCase()
        : derivePskHex(passphrase, network.ssid);
      return { psk_hex, fingerprint: cred.fingerprint };
    }
    case "peap-mschapv2":
      return {
        identity: payload.identity!,
        password_nthash: deriveNtHash(payload.password!),
        fingerprint: cred.fingerprint,
      };
    case "eap-tls":
      return {
        client_cert: payload.client_cert!,
        private_key: payload.private_key!,
        ca_cert: payload.ca_cert,
        fingerprint: cred.fingerprint,
      };
  }
}

/**
 * Build the template context for one network. In redact mode, secret-derived
 * values are replaced with `<redacted:fp xxxxxxxx>` placeholders (PRD R7) so a
 * browser preview never receives real secret material.
 */
export function buildContext(
  network: NetworkDoc,
  forms: DerivedForms,
  redact: boolean,
): TemplateContext {
  const fp = forms.fingerprint ?? "unknown";
  const val = (key: (typeof SECRET_KEYS)[number], real: string | undefined) => {
    if (real === undefined) return undefined;
    return redact ? `<redacted:fp ${fp}>` : real;
  };

  return {
    ssid: network.ssid,
    name: network.name,
    security: network.security,
    priority: network.priority,
    scan_ssid: network.scan_ssid,
    psk_hex: val("psk_hex", forms.psk_hex),
    identity: val("identity", forms.identity),
    password_nthash: val("password_nthash", forms.password_nthash),
    client_cert: val("client_cert", forms.client_cert),
    private_key: val("private_key", forms.private_key),
    // ca_cert is a non-secret path; never redacted.
    ca_cert: forms.ca_cert ?? network.variables.ca_cert,
    ...network.variables,
  };
}

/** Render a single network's block using its active template. */
export async function renderNetwork(
  ctx: AppContext,
  network: NetworkDoc,
  redact: boolean,
): Promise<string> {
  const template = await ctx.c.templates.findOne({
    name: network.template_name,
    status: "active",
  });
  if (!template) {
    throw badRequest(`Network '${network.name}' references template '${network.template_name}' which has no active version`);
  }
  const cred = await ctx.c.credentials.findOne({ network_name: network.name, status: "active" });
  if (network.security !== "open" && !cred) {
    throw badRequest(`Network '${network.name}' has no credential set`);
  }
  const forms = deriveForms(ctx, network, cred);
  const context = buildContext(network, forms, redact);
  return renderTemplate(template.body, context);
}

export interface RenderOutput {
  text: string;
  fingerprint: string;
}

/**
 * Render a whole bundle: optional base (global) template, then each network's
 * block in the bundle's declared order (priority-aware ordering is the
 * caller's responsibility when composing the bundle).
 */
export async function renderBundle(
  ctx: AppContext,
  bundleName: string,
  redact: boolean,
): Promise<RenderOutput> {
  const bundle = await ctx.c.bundles.findOne({ name: bundleName });
  if (!bundle) throw notFound("Bundle not found");

  const parts: string[] = [];

  if (bundle.base_template_name) {
    const base = await ctx.c.templates.findOne({
      name: bundle.base_template_name,
      status: "active",
    });
    if (!base) throw badRequest(`Base template '${bundle.base_template_name}' has no active version`);
    // Base/global section is literal text; render with an empty context.
    parts.push(renderTemplate(base.body, {} as TemplateContext).trimEnd());
  }

  for (const netName of bundle.network_names) {
    const net = await ctx.c.networks.findOne({ name: netName });
    if (!net) throw badRequest(`Bundle references missing network '${netName}'`);
    parts.push((await renderNetwork(ctx, net, redact)).trimEnd());
  }

  const text = parts.join("\n\n") + "\n";
  return { text, fingerprint: fingerprint(text) };
}
