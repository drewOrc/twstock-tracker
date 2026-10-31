/* One origin, three namespaces:
 *   /api/market/*  通用層 (shared market knowledge)       -> engine(path)
 *   /api/me/*      個人化層 (my lists, alerts)              -> engine(path) for /watchlist(s), /alerts
 *   /api/admin/*   admin-only operations                    -> admin(path)
 *   /api/auth/*    login / logout / me                      -> auth(path)
 *   /api/crm/*     Stock CRM, proxied with my identity      -> crm(path)
 */
import { useCallback, useEffect, useState } from "react";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export interface ReqOpts {
  method?: "GET" | "POST" | "PATCH" | "PUT" | "DELETE";
  body?: unknown;
}

/** Called on any 401 so the app can show the login screen. */
let onUnauthorized: (() => void) | null = null;
export const setUnauthorizedHandler = (fn: (() => void) | null) => (onUnauthorized = fn);

async function request<T = any>(url: string, opts: ReqOpts = {}): Promise<T> {
  const res = await fetch(url, {
    method: opts.method ?? "GET",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: any = {};
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text };
  }
  if (!res.ok) {
    if (res.status === 401 && !url.startsWith("/api/auth/login") && onUnauthorized) onUnauthorized();
    const detail = data?.detail;
    const msg = typeof detail === "string" ? detail : JSON.stringify(detail ?? data).slice(0, 200);
    throw new ApiError(res.status, msg || `${res.status} ${res.statusText}`);
  }
  return data as T;
}

const ME_PREFIXES = ["/watchlist", "/alerts"];
const isMe = (p: string) => ME_PREFIXES.some((x) => p === x || p.startsWith(x + "/") || p.startsWith(x + "?") || p.startsWith(x + "s"));

/** Engine call; routes to /api/me for personal paths and /api/market for everything else. */
export const engine = <T = any>(path: string, opts?: ReqOpts) => request<T>(`/api/${isMe(path) ? "me" : "market"}${path}`, opts);
export const admin = <T = any>(path: string, opts?: ReqOpts) => request<T>(`/api/admin${path}`, opts);
export const auth = <T = any>(path: string, opts?: ReqOpts) => request<T>(`/api/auth${path}`, opts);
export const crm = <T = any>(path: string, opts?: ReqOpts) => request<T>(`/api/crm${path}`, opts);
export const publicApi = <T = any>(path: string, opts?: ReqOpts) => request<T>(`/api${path}`, opts);

/** Minimal async-data hook with optional polling. `deps` re-run the loader; `interval` (ms) polls. */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[], interval?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  const reload = useCallback(async () => {
    try {
      setData(await loader());
      setError(null);
    } catch (e: any) {
      setError(e?.message ?? String(e));
    } finally {
      setLoading(false);
    }
  }, deps);
  useEffect(() => {
    reload();
    if (!interval) return;
    const t = setInterval(reload, interval);
    return () => clearInterval(t);
  }, [reload, interval]);
  return { data, error, loading, reload, setData };
}
