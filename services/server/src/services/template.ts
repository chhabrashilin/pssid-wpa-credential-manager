import nunjucks from "nunjucks";
import { badRequest } from "../util/errors.js";

/**
 * Jinja-style template rendering in a locked-down sandbox (PRD 9.3).
 *
 * nunjucks is Jinja2-compatible enough for wpa_supplicant blocks. We harden it:
 *  - autoescape OFF (this is a config file, not HTML)
 *  - throwOnUndefined ON (fail closed on undefined variables)
 *  - NO filesystem loader (templates come from the DB as strings)
 *  - a static lint that rejects constructs enabling file access, template
 *    inheritance/includes, or prototype-walking sandbox escapes.
 */

const env = new nunjucks.Environment(null, {
  autoescape: false,
  throwOnUndefined: true,
});

/** Tokens that must never appear in a stored template (sandbox escape / file access). */
const FORBIDDEN_PATTERNS: Array<[RegExp, string]> = [
  [/\{%\s*(include|import|extends|from)\b/i, "template includes/inheritance are not allowed"],
  [/constructor/i, "attribute 'constructor' is not allowed"],
  [/__proto__|prototype|__globals__|__builtins__/i, "prototype/global access is not allowed"],
  [/\bprocess\b|\brequire\b|\bglobal\b/i, "runtime globals are not allowed"],
];

export function lintTemplate(body: string): void {
  for (const [re, msg] of FORBIDDEN_PATTERNS) {
    if (re.test(body)) throw badRequest(`Template rejected: ${msg}`);
  }
}

/** The variable contract exposed to templates (PRD 9.3). */
export interface TemplateContext {
  ssid: string;
  name: string;
  security: string;
  priority: number;
  scan_ssid: number;
  psk_hex?: string;
  identity?: string;
  password_nthash?: string;
  ca_cert?: string;
  client_cert?: string;
  private_key?: string;
  [extra: string]: string | number | undefined;
}

/**
 * Render a template body against a context. Only string/number primitives are
 * placed in the context, limiting the surface for attribute-walking escapes.
 * Undefined variables throw (fail closed).
 */
export function renderTemplate(body: string, context: TemplateContext): string {
  lintTemplate(body);
  try {
    return env.renderString(body, context as Record<string, unknown>);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    throw badRequest(`Template render failed: ${msg}`);
  }
}

// --- Output validation against a wpa_supplicant grammar subset (PRD 9.3) ---

/** A conservative allowlist of wpa_supplicant network-block keys, for misspell warnings. */
const KNOWN_KEYS = new Set([
  "ssid", "scan_ssid", "bssid", "priority", "mode", "frequency", "key_mgmt",
  "auth_alg", "proto", "pairwise", "group", "psk", "wep_key0", "wep_tx_keyidx",
  "eap", "identity", "anonymous_identity", "password", "ca_cert", "ca_cert2",
  "client_cert", "client_cert2", "private_key", "private_key2",
  "private_key_passwd", "private_key2_passwd", "phase1", "phase2",
  "subject_match", "altsubject_match", "domain_suffix_match", "eapol_flags",
  "disabled", "id_str", "pcsc", "pin",
]);

/** Global (top-level) wpa_supplicant keys allowed outside network blocks. */
const GLOBAL_KEYS = new Set([
  "ctrl_interface", "ctrl_interface_group", "update_config", "country",
  "ap_scan", "eapol_version", "fast_reauth", "pmf", "p2p_disabled",
]);

export interface ValidationResult {
  ok: boolean;
  errors: string[];
  warnings: string[];
}

/**
 * Validate rendered wpa_supplicant output: balanced network={...} blocks,
 * key=value lines, and warn on unknown keys. Errors block activation;
 * warnings do not (PRD 9.3).
 */
export function validateWpaSupplicant(rendered: string): ValidationResult {
  const errors: string[] = [];
  const warnings: string[] = [];
  const lines = rendered.split(/\r?\n/);

  let depth = 0;
  lines.forEach((rawLine, i) => {
    const line = rawLine.trim();
    const lineNo = i + 1;
    if (!line || line.startsWith("#")) return;

    if (/^network\s*=\s*\{$/.test(line)) {
      depth++;
      return;
    }
    if (line === "}") {
      depth--;
      if (depth < 0) errors.push(`Line ${lineNo}: unexpected '}'`);
      return;
    }

    // Otherwise expect key=value.
    const m = /^([a-zA-Z0-9_]+)\s*=\s*(.+)$/.exec(line);
    if (!m) {
      errors.push(`Line ${lineNo}: not a key=value line: "${line}"`);
      return;
    }
    const key = m[1]!;
    const inBlock = depth > 0;
    const known = inBlock ? KNOWN_KEYS.has(key) : GLOBAL_KEYS.has(key);
    if (!known) {
      warnings.push(
        `Line ${lineNo}: unknown ${inBlock ? "network" : "global"} key '${key}'`,
      );
    }
  });

  if (depth > 0) errors.push(`Unbalanced network block: ${depth} unclosed '{'`);
  return { ok: errors.length === 0, errors, warnings };
}

/** A synthetic context with every contract variable populated, for validation. */
export function dummyContext(): TemplateContext {
  return {
    ssid: "ExampleSSID",
    name: "example",
    security: "wpa-eap-peap-mschapv2",
    priority: 5,
    scan_ssid: 0,
    psk_hex: "0".repeat(64),
    identity: "example-identity",
    password_nthash: "0".repeat(32),
    ca_cert: "/etc/ssl/certs/example.pem",
    client_cert: "/etc/ssl/certs/client.pem",
    private_key: "/etc/ssl/private/client.key",
  };
}

/**
 * Validate a template body for activation: it must lint clean, render against
 * a synthetic full context, and produce syntactically valid wpa_supplicant
 * output. Returns the grammar warnings (non-blocking); throws on any error.
 */
export function validateTemplateBody(body: string): ValidationResult {
  const rendered = renderTemplate(body, dummyContext());
  return validateWpaSupplicant(rendered);
}
