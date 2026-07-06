import fs from "node:fs";
import type { Role } from "./principal.js";

/**
 * Role mapping file (PRD 9.6):
 *   { "groups": { "credmgr-admin": "write", "credmgr-view": "read" } }
 * Maps OIDC group claims to app roles. Highest role wins when a user is in
 * several groups.
 */
export interface RoleMap {
  groups: Record<string, Role>;
}

const RANK: Record<Role, number> = { read: 1, write: 2 };

export function loadRoleMap(path: string): RoleMap {
  if (!path || !fs.existsSync(path)) {
    return { groups: {} };
  }
  const parsed = JSON.parse(fs.readFileSync(path, "utf8")) as Partial<RoleMap>;
  const groups: Record<string, Role> = {};
  for (const [group, role] of Object.entries(parsed.groups ?? {})) {
    if (role === "read" || role === "write") groups[group] = role;
  }
  return { groups };
}

/** Resolve the effective role from a user's group claims. */
export function roleForGroups(map: RoleMap, groups: string[]): Role | null {
  let best: Role | null = null;
  for (const g of groups) {
    const role = map.groups[g];
    if (role && (!best || RANK[role] > RANK[best])) best = role;
  }
  return best;
}
