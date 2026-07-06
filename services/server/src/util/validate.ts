import { z } from "zod";
import { badRequest } from "./errors.js";

/** RFC 1123 label: lowercase alnum and hyphens, 1-63 chars, no leading/trailing hyphen. */
export const rfc1123Label = z
  .string()
  .regex(
    /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$/,
    "must be a lowercase RFC 1123 label (a-z, 0-9, hyphen)",
  );

export const securityType = z.enum([
  "wpa-psk",
  "wpa-eap-peap-mschapv2",
  "eap-tls",
  "open",
]);

/** SSID: 1-32 bytes when UTF-8 encoded. */
export const ssidSchema = z
  .string()
  .min(1, "SSID required")
  .refine((s) => Buffer.byteLength(s, "utf8") <= 32, "SSID must be ≤ 32 bytes");

export const networkCreateSchema = z.object({
  name: rfc1123Label,
  ssid: ssidSchema,
  security: securityType,
  priority: z.number().int().min(0).max(255).default(0),
  scan_ssid: z.union([z.literal(0), z.literal(1)]).default(0),
  notes: z.string().max(2000).optional(),
  template_name: rfc1123Label,
  variables: z.record(z.string(), z.string()).default({}),
});

export const networkUpdateSchema = networkCreateSchema.partial().omit({ name: true });

export const templateCreateSchema = z.object({
  name: rfc1123Label,
  body: z.string().min(1, "template body required").max(100_000),
});

export const bundleSchema = z.object({
  name: rfc1123Label,
  network_names: z.array(rfc1123Label),
  base_template_name: rfc1123Label.optional(),
});

export const tokenCreateSchema = z.object({
  name: z.string().min(1).max(200),
  scopes: z.array(rfc1123Label).min(1, "at least one bundle scope required"),
  expires_in_days: z.number().int().min(1).max(3650).default(365),
});

/** Parse and throw a 400 HttpError with a readable message on failure. */
export function parse<S extends z.ZodTypeAny>(schema: S, data: unknown): z.infer<S> {
  const result = schema.safeParse(data);
  if (!result.success) {
    const first = result.error.issues[0];
    const path = first?.path.join(".");
    throw badRequest(path ? `${path}: ${first?.message}` : (first?.message ?? "Invalid request"));
  }
  return result.data;
}
