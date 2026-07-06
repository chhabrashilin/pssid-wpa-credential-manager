/** Thin fetch wrapper for the credential-manager API. Throws ApiError on non-2xx. */
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api/v1${path}`, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
  });
  const ct = res.headers.get("content-type") ?? "";
  const isJson = ct.includes("application/json");
  const payload = isJson ? await res.json() : await res.text();
  if (!res.ok) {
    const msg = isJson && payload?.message ? payload.message : `HTTP ${res.status}`;
    throw new ApiError(res.status, msg);
  }
  return payload as T;
}

export const api = {
  get: <T>(p: string) => request<T>("GET", p),
  post: <T>(p: string, b?: unknown) => request<T>("POST", p, b ?? {}),
  put: <T>(p: string, b?: unknown) => request<T>("PUT", p, b ?? {}),
  del: <T>(p: string) => request<T>("DELETE", p),
  // Plain-text endpoints (preview).
  text: async (p: string): Promise<string> => {
    const res = await fetch(`/api/v1${p}`, { credentials: "same-origin" });
    const body = await res.text();
    if (!res.ok) throw new ApiError(res.status, body || `HTTP ${res.status}`);
    return body;
  },
};
