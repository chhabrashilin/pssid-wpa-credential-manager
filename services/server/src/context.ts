import type { AppConfig } from "./config.js";
import type { Collections } from "./db.js";
import type { RoleMap } from "./auth/roles.js";

/** Shared dependencies handed to every route factory. */
export interface AppContext {
  cfg: AppConfig;
  c: Collections;
  kek: Buffer;
  roleMap: RoleMap;
}
