/** The authenticated caller for a request. */
export type Role = "read" | "write";

export interface Principal {
  actor: string; // user email/sub, or token id
  actorType: "user" | "token";
  role: Role | null; // null for anonymous / no-access
  tokenScopes?: string[]; // bundle names, only for machine tokens
}

// Augment Express Request with the resolved principal.
declare global {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace Express {
    interface Request {
      principal?: Principal;
    }
  }
}
