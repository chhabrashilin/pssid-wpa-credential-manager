import type { NextFunction, Request, Response } from "express";
import type { AppConfig } from "../config.js";
import { forbidden, unauthorized } from "../util/errors.js";
import type { Principal, Role } from "./principal.js";
import { roleForGroups, type RoleMap } from "./roles.js";

/**
 * A function that derives the user Principal from a request. Injectable so
 * tests can simulate roles without a full OIDC round-trip; production uses
 * `defaultUserResolver`.
 */
export type AuthResolver = (req: Request) => Principal;

/**
 * Default user-principal resolver.
 *  - SSO on:  read `req.oidc` (express-openid-connect); map group claims.
 *  - SSO off: lab mode - write role if OPEN_WRITE, else read-only.
 */
export function defaultUserResolver(cfg: AppConfig, roleMap: RoleMap): AuthResolver {
  return (req: Request): Principal => {
    if (!cfg.ssoEnabled) {
      return {
        actor: "local",
        actorType: "user",
        role: cfg.openWrite ? "write" : "read",
      };
    }
    // express-openid-connect attaches `oidc` to the request.
    const oidc = (req as unknown as { oidc?: OidcContext }).oidc;
    if (!oidc?.isAuthenticated?.()) {
      return { actor: "anonymous", actorType: "user", role: null };
    }
    const user = oidc.user ?? {};
    const actor = String(user.email ?? user.sub ?? "unknown");
    const groups = extractGroups(user);
    return { actor, actorType: "user", role: roleForGroups(roleMap, groups) };
  };
}

interface OidcContext {
  isAuthenticated?: () => boolean;
  user?: Record<string, unknown>;
}

function extractGroups(user: Record<string, unknown>): string[] {
  const raw = user.groups ?? user.roles ?? [];
  if (Array.isArray(raw)) return raw.map(String);
  if (typeof raw === "string") return raw.split(/[,\s]+/).filter(Boolean);
  return [];
}

/**
 * Middleware factory: resolve and attach the user principal to every request.
 * Machine-token routes override this with `requireToken`.
 */
export function attachPrincipal(resolver: AuthResolver) {
  return (req: Request, _res: Response, next: NextFunction): void => {
    req.principal = resolver(req);
    next();
  };
}

const RANK: Record<Role, number> = { read: 1, write: 2 };

/**
 * Guard a route by minimum role. On denial, throws (the audit-on-deny happens
 * in the wrapper so we don't couple this to a specific collection here).
 */
export function requireRole(min: Role) {
  return (req: Request, _res: Response, next: NextFunction): void => {
    const p = req.principal;
    if (!p || p.role === null) {
      next(unauthorized("Authentication required"));
      return;
    }
    if (RANK[p.role] < RANK[min]) {
      next(forbidden(`Requires ${min} role`));
      return;
    }
    next();
  };
}
