import { Collection, Db, MongoClient } from "mongodb";
import type {
  AuditEventDoc,
  BundleDoc,
  CredentialDoc,
  NetworkDoc,
  RenderDoc,
  SettingsDoc,
  TemplateDoc,
  TokenDoc,
} from "./models/types.js";

export interface Collections {
  networks: Collection<NetworkDoc>;
  credentials: Collection<CredentialDoc>;
  templates: Collection<TemplateDoc>;
  bundles: Collection<BundleDoc>;
  renders: Collection<RenderDoc>;
  tokens: Collection<TokenDoc>;
  audit: Collection<AuditEventDoc>;
  settings: Collection<SettingsDoc>;
}

let client: MongoClient | undefined;
let db: Db | undefined;
let collections: Collections | undefined;

export async function connectDb(mongoUrl: string, dbName: string): Promise<Collections> {
  client = new MongoClient(mongoUrl, { serverSelectionTimeoutMS: 5000 });
  await client.connect();
  db = client.db(dbName);

  collections = {
    networks: db.collection<NetworkDoc>("networks"),
    credentials: db.collection<CredentialDoc>("credentials"),
    templates: db.collection<TemplateDoc>("templates"),
    bundles: db.collection<BundleDoc>("bundles"),
    renders: db.collection<RenderDoc>("renders"),
    tokens: db.collection<TokenDoc>("tokens"),
    audit: db.collection<AuditEventDoc>("audit_events"),
    settings: db.collection<SettingsDoc>("settings"),
  };

  await ensureIndexes(collections);
  return collections;
}

async function ensureIndexes(c: Collections): Promise<void> {
  await c.networks.createIndex({ name: 1 }, { unique: true });
  await c.credentials.createIndex({ network_name: 1, version: 1 }, { unique: true });
  await c.credentials.createIndex({ network_name: 1, status: 1 });
  await c.templates.createIndex({ name: 1, version: 1 }, { unique: true });
  await c.bundles.createIndex({ name: 1 }, { unique: true });
  await c.renders.createIndex({ bundle_name: 1, version: 1 }, { unique: true });
  await c.tokens.createIndex({ id: 1 }, { unique: true });
  await c.tokens.createIndex({ hash: 1 });
  await c.audit.createIndex({ ts: -1 });
  await c.audit.createIndex({ actor: 1, action: 1, object: 1 });
}

export function getCollections(): Collections {
  if (!collections) throw new Error("Database not connected. Call connectDb() first.");
  return collections;
}

export async function pingDb(): Promise<boolean> {
  if (!db) return false;
  try {
    await db.command({ ping: 1 });
    return true;
  } catch {
    return false;
  }
}

export async function closeDb(): Promise<void> {
  await client?.close();
  client = undefined;
  db = undefined;
  collections = undefined;
}
