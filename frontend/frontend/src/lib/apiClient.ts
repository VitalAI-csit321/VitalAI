// Low-level HTTP client for the VitalAI backend.
//
// This is the ONLY file that knows the wire format (JWT bearer, form-encoded
// login, the /api/v1 prefix, the { items, total, limit, offset } page envelope).
// Everything above it works in domain types — see src/api/*. Swapping backends
// later means changing adapters in src/api, not this transport.

const BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ??
  "http://localhost:8000";

const TOKEN_KEY = "vitalai.token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token);
  else localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `Request failed (${status})`);
    this.status = status;
    this.detail = detail;
  }
}

// FastAPI's own 422s carry `detail` as a list of {loc, msg} pydantic errors,
// not a string. Surfacing "Request failed (422)" (or worse, an unrelated
// canned message a caller wrote for a different status) hides the actual
// validation reason from the user. Use this in a catch block instead of
// guessing a message from the HTTP status alone.
export function describeApiError(err: unknown, fallback: string): string {
  if (!(err instanceof ApiError)) return fallback;
  if (typeof err.detail === "string") return err.detail;
  if (Array.isArray(err.detail)) {
    const messages = err.detail
      .map((e) => (e && typeof e === "object" && "msg" in e ? String((e as { msg: unknown }).msg) : null))
      .filter((m): m is string => m !== null);
    if (messages.length) return messages.join("; ");
  }
  return fallback;
}

function authHeaders(): Record<string, string> {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function parse(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

async function handle(res: Response): Promise<unknown> {
  const body = await parse(res);
  if (!res.ok) {
    const detail =
      body && typeof body === "object" && "detail" in body
        ? (body as { detail: unknown }).detail
        : body;
    throw new ApiError(res.status, detail);
  }
  return body;
}

export async function apiGet<T>(
  path: string,
  params?: Record<string, unknown>,
): Promise<T> {
  const url = new URL(BASE_URL + path);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null || value === "") continue;
      if (Array.isArray(value)) {
        value.forEach((v) => url.searchParams.append(key, String(v)));
      } else {
        url.searchParams.set(key, String(value));
      }
    }
  }
  const res = await fetch(url.toString(), { headers: { ...authHeaders() } });
  return handle(res) as Promise<T>;
}

export async function apiPost<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE_URL + path, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return handle(res) as Promise<T>;
}

export async function apiPostForm<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(BASE_URL + path, {
    method: "POST",
    headers: { ...authHeaders() }, // no Content-Type — browser sets the multipart boundary
    body: form,
  });
  return handle(res) as Promise<T>;
}

export async function apiPatch<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE_URL + path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return handle(res) as Promise<T>;
}

export async function apiDelete<T>(path: string): Promise<T> {
  const res = await fetch(BASE_URL + path, {
    method: "DELETE",
    headers: { ...authHeaders() },
  });
  return handle(res) as Promise<T>;
}

// Login is the one endpoint that is form-encoded (OAuth2 password flow), with
// the email carried in a field named `username`. Isolated here so no other
// caller has to remember that quirk.
export async function apiLoginForm(email: string, password: string): Promise<{ access_token: string }> {
  const form = new URLSearchParams();
  form.set("username", email);
  form.set("password", password);
  const res = await fetch(BASE_URL + "/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form.toString(),
  });
  return handle(res) as Promise<{ access_token: string }>;
}

// The shared pagination envelope returned by every list endpoint.
export interface ApiPage<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}
