import type { Request, Response } from "express";
import { describe, expect, it, vi } from "vitest";
import { defaultUserResolver, requireRole } from "../src/auth/middleware.js";
import { requireToken } from "../src/auth/tokens.js";
import { roleForGroups, type RoleMap } from "../src/auth/roles.js";
import { tokenHash } from "../src/crypto/fingerprint.js";
import { HttpError } from "../src/util/errors.js";
import type { AppConfig } from "../src/config.js";
import type { Collections } from "../src/db.js";
import type { TokenDoc } from "../src/models/types.js";

const cfg = (over: Partial<AppConfig> = {}): AppConfig =>
  ({ ssoEnabled: false, openWrite: false, ...over }) as AppConfig;

const roleMap: RoleMap = { groups: { "credmgr-admin": "write", "credmgr-view": "read" } };

// --- Role resolution ---------------------------------------------------------

describe("defaultUserResolver - lab mode (SSO off)", () => {
  it("read-only by default", () => {
    const p = defaultUserResolver(cfg(), roleMap)({} as Request);
    expect(p.role).toBe("read");
  });
  it("write when OPEN_WRITE=true", () => {
    const p = defaultUserResolver(cfg({ openWrite: true }), roleMap)({} as Request);
    expect(p.role).toBe("write");
  });
});

describe("defaultUserResolver - SSO mode", () => {
  const resolver = defaultUserResolver(cfg({ ssoEnabled: true }), roleMap);
  const reqWith = (oidc: unknown) => ({ oidc }) as unknown as Request;

  it("anonymous when unauthenticated", () => {
    const p = resolver(reqWith({ isAuthenticated: () => false }));
    expect(p.role).toBeNull();
  });
  it("maps admin group to write", () => {
    const p = resolver(
      reqWith({ isAuthenticated: () => true, user: { email: "a@x", groups: ["credmgr-admin"] } }),
    );
    expect(p).toMatchObject({ actor: "a@x", role: "write" });
  });
  it("maps view group to read", () => {
    const p = resolver(
      reqWith({ isAuthenticated: () => true, user: { sub: "s1", groups: ["credmgr-view"] } }),
    );
    expect(p).toMatchObject({ actor: "s1", role: "read" });
  });
  it("no role when in no mapped group", () => {
    const p = resolver(reqWith({ isAuthenticated: () => true, user: { email: "n@x", groups: ["other"] } }));
    expect(p.role).toBeNull();
  });
});

describe("roleForGroups - highest role wins", () => {
  it("write beats read", () => {
    expect(roleForGroups(roleMap, ["credmgr-view", "credmgr-admin"])).toBe("write");
  });
});

// --- requireRole guard -------------------------------------------------------

function runGuard(min: "read" | "write", principalRole: "read" | "write" | null | undefined) {
  const req = { principal: principalRole === undefined ? undefined : { role: principalRole } } as Request;
  let err: unknown;
  requireRole(min)(req, {} as Response, (e?: unknown) => (err = e));
  return err;
}

describe("requireRole (authz matrix)", () => {
  it("no principal → 401", () => {
    expect((runGuard("read", undefined) as HttpError).status).toBe(401);
  });
  it("null role → 401", () => {
    expect((runGuard("read", null) as HttpError).status).toBe(401);
  });
  it("read user on write route → 403", () => {
    expect((runGuard("write", "read") as HttpError).status).toBe(403);
  });
  it("read user on read route → allowed", () => {
    expect(runGuard("read", "read")).toBeUndefined();
  });
  it("write user on write route → allowed", () => {
    expect(runGuard("write", "write")).toBeUndefined();
  });
  it("write user on read route → allowed", () => {
    expect(runGuard("read", "write")).toBeUndefined();
  });
});

// --- Machine token middleware ------------------------------------------------

function fakeCollections(token?: Partial<TokenDoc>): Collections {
  const doc = token
    ? ({ id: "tok1", name: "t", scopes: ["campus"], expires_at: new Date(Date.now() + 1e9), ...token } as TokenDoc)
    : null;
  return {
    tokens: {
      findOne: vi.fn(async () => doc),
      updateOne: vi.fn(async () => ({})),
    },
    audit: { insertOne: vi.fn(async () => ({})) },
  } as unknown as Collections;
}

async function runToken(c: Collections, auth: string | undefined, bundle = "campus") {
  const req = {
    header: (h: string) => (h.toLowerCase() === "authorization" ? auth : undefined),
    params: { name: bundle },
    path: `/bundles/${bundle}/render`,
  } as unknown as Request;
  let err: unknown;
  await requireToken(c)(req, {} as Response, (e?: unknown) => (err = e));
  return { err, req };
}

describe("requireToken (machine pull authz)", () => {
  const valid = "credmgr_secretvalue";
  const withValid = () => fakeCollections({ hash: tokenHash(valid) });

  it("missing bearer → 401", async () => {
    const { err } = await runToken(withValid(), undefined);
    expect((err as HttpError).status).toBe(401);
  });
  it("unknown/invalid token → 401", async () => {
    const { err } = await runToken(fakeCollections(), `Bearer nope`);
    expect((err as HttpError).status).toBe(401);
  });
  it("expired token → 401", async () => {
    const c = fakeCollections({ hash: tokenHash(valid), expires_at: new Date(Date.now() - 1000) });
    const { err } = await runToken(c, `Bearer ${valid}`);
    expect((err as HttpError).status).toBe(401);
  });
  it("revoked token → 401", async () => {
    const c = fakeCollections({ hash: tokenHash(valid), revoked_at: new Date() });
    const { err } = await runToken(c, `Bearer ${valid}`);
    expect((err as HttpError).status).toBe(401);
  });
  it("out-of-scope bundle → 403", async () => {
    const { err } = await runToken(withValid(), `Bearer ${valid}`, "other-bundle");
    expect((err as HttpError).status).toBe(403);
  });
  it("valid, in-scope → sets read token principal", async () => {
    const { err, req } = await runToken(withValid(), `Bearer ${valid}`);
    expect(err).toBeUndefined();
    expect(req.principal).toMatchObject({ actorType: "token", role: "read", actor: "tok1" });
  });
});
