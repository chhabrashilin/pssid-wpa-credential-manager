/**
 * Document shapes for the `credmgr` MongoDB database (PRD Section 10).
 * Secret fields are always stored in the envelope-encrypted form; the raw
 * value never lives on any document.
 */

export type SecurityType =
  | "wpa-psk"
  | "wpa-eap-peap-mschapv2"
  | "eap-tls"
  | "open";

export type CredentialType = "psk" | "peap-mschapv2" | "eap-tls";

export interface NetworkDoc {
  name: string; // unique, RFC 1123 label
  ssid: string; // 1-32 bytes
  security: SecurityType;
  priority: number;
  scan_ssid: 0 | 1;
  notes?: string;
  template_name: string;
  variables: Record<string, string>; // non-secret extra template vars
  credential_version: number; // 0 = none set yet
  created_by: string;
  created_at: Date;
  updated_at: Date;
}

/** Envelope-encrypted secret blob (see crypto/envelope.ts). */
export interface SealedFields {
  payload_ct: string;
  payload_iv: string;
  payload_tag: string;
  dek_wrapped: string;
}

export interface CredentialDoc extends SealedFields {
  network_name: string;
  version: number;
  type: CredentialType;
  fingerprint: string; // sha256[:8] of the raw secret material
  status: "active" | "superseded";
  created_by: string;
  created_at: Date;
}

export interface TemplateDoc {
  name: string;
  version: number;
  body: string;
  status: "draft" | "active";
  created_by: string;
  created_at: Date;
}

export interface BundleDoc {
  name: string;
  network_names: string[];
  base_template_name?: string;
  render_version: number;
  created_by: string;
  updated_at: Date;
}

export interface RenderDoc extends SealedFields {
  bundle_name: string;
  version: number;
  fingerprint: string; // sha256[:8] of the rendered artifact
  rendered_by: string;
  rendered_at: Date;
}

export interface TokenDoc {
  id: string;
  name: string;
  hash: string; // sha256 of the token value
  scopes: string[]; // bundle names the token may pull
  expires_at: Date;
  created_by: string;
  created_at: Date;
  revoked_at?: Date;
  last_used_at?: Date;
}

export type AuditAction =
  | "network.create"
  | "network.update"
  | "network.delete"
  | "credential.set"
  | "credential.rotate"
  | "credential.rollback"
  | "template.create"
  | "template.update"
  | "template.activate"
  | "bundle.create"
  | "bundle.update"
  | "bundle.delete"
  | "bundle.render"
  | "render.pull"
  | "token.create"
  | "token.revoke"
  | "auth.denied";

export interface AuditEventDoc {
  ts: Date;
  actor: string; // user sub/email or token id
  actor_type: "user" | "token";
  action: AuditAction;
  object: string;
  meta: Record<string, unknown>; // fingerprints only, never secret values
}

export interface SettingsDoc {
  _id: "app";
  rotation_warn_days: number;
  kek_version: number;
}
