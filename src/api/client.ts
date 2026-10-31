/** Runtime API origin and the one request function every call goes through. */

export function apiOrigin(): string {
  const w = (typeof window !== 'undefined' ? window : undefined) as { __ENV__?: Record<string, string> } | undefined;
  const fromEnv = (import.meta as unknown as { env?: Record<string, string> }).env?.VITE_API_URL;
  return (w?.__ENV__?.VITE_API_URL ?? fromEnv ?? '').replace(/\/$/, '');
}

export interface FieldError { loc: (string | number)[]; msg: string }

export class FastApiError extends Error {
  status: number;
  code: string | null;
  detail: string | null;
  source: string | null;
  rules: string[] | null;
  fields: FieldError[];

  constructor(status: number, body: unknown) {
    const b = (body && typeof body === 'object' ? body : {}) as Record<string, unknown>;
    const detail = typeof b.detail === 'string' ? b.detail : null;
    super(detail ?? (typeof b.error === 'string' ? b.error : `HTTP ${status}`));
    this.name = 'FastApiError';
    this.status = status;
    this.code = typeof b.error === 'string' ? b.error : null;
    this.detail = detail;
    this.source = typeof b.source === 'string' ? b.source : null;
    this.rules = Array.isArray(b.rules) ? b.rules.map(String) : null;
    this.fields = Array.isArray(b.detail)
      ? (b.detail as Record<string, unknown>[]).map((e) => ({
        loc: Array.isArray(e.loc) ? (e.loc as (string | number)[]) : [],
        msg: String(e.msg ?? ''),
      }))
      : [];
  }
}

export type Method = 'GET' | 'POST' | 'PUT' | 'DELETE';

/** Any URL of the platform API (the session cookie is host-only on the API host: credentials always). */
export async function requestUrl<T>(method: Method, url: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const init: RequestInit = { method, credentials: 'include', signal };
  if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' };
    init.body = JSON.stringify(body);
  }
  const res = await fetch(url, init);
  const text = await res.text();
  let parsed: unknown = null;
  if (text) {
    try { parsed = JSON.parse(text); } catch { parsed = null; }
  }
  if (!res.ok) throw new FastApiError(res.status, parsed);
  return parsed as T;
}

/** `path` is relative to the module API (`/api/fast`). */
export function request<T>(method: Method, path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  return requestUrl<T>(method, `${apiOrigin()}/api/fast${path}`, body, signal);
}
