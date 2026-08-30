/**
 * Typed API client (openapi-fetch) with an auth layer:
 *  - attaches the in-memory access token as a Bearer header
 *  - on a 401, transparently refreshes once and retries
 *  - sends the double-submit CSRF header on the cookie-authed auth routes
 *
 * Regenerate `schema.d.ts` with `npm run gen:api` (needs the API running).
 */

import createClient, { type Middleware } from 'openapi-fetch';

import type { paths } from './schema';

// The OpenAPI paths already include the `/api` prefix, so the base is just the
// origin. Default to the page's own origin (dev proxies `/api`; prod is same
// origin). Set VITE_API_ORIGIN only to target a separate API host.
const ORIGIN = (
  import.meta.env.VITE_API_ORIGIN ?? (typeof window !== 'undefined' ? window.location.origin : '')
).replace(/\/$/, '');

let accessToken: string | null = null;
let onAuthLost: (() => void) | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}
export function getAccessToken(): string | null {
  return accessToken;
}
export function setAuthLostHandler(fn: () => void): void {
  onAuthLost = fn;
}

function readCookie(name: string): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return match ? decodeURIComponent(match[1]) : null;
}

/** POST /auth/refresh outside the middleware (so it can't recurse). */
async function refreshAccessToken(): Promise<boolean> {
  const csrf = readCookie('tvtimes_csrf');
  if (!csrf) return false;
  const res = await fetch(`${ORIGIN}/api/auth/refresh`, {
    method: 'POST',
    headers: { 'X-CSRF-Token': csrf },
  });
  if (!res.ok) return false;
  const body = (await res.json()) as { access_token: string };
  accessToken = body.access_token;
  return true;
}

const authMiddleware: Middleware = {
  onRequest({ request }) {
    if (accessToken && !request.headers.has('Authorization')) {
      request.headers.set('Authorization', `Bearer ${accessToken}`);
    }
    const url = new URL(request.url);
    if (url.pathname.endsWith('/auth/refresh') || url.pathname.endsWith('/auth/logout')) {
      const csrf = readCookie('tvtimes_csrf');
      if (csrf) request.headers.set('X-CSRF-Token', csrf);
    }
    return request;
  },
  async onResponse({ request, response }) {
    if (response.status !== 401 || request.headers.has('X-Retry')) return response;
    const url = new URL(request.url);
    if (url.pathname.endsWith('/auth/refresh') || url.pathname.endsWith('/auth/login')) {
      return response;
    }
    const ok = await refreshAccessToken();
    if (!ok) {
      onAuthLost?.();
      return response;
    }
    const retry = new Request(request, { headers: request.headers });
    retry.headers.set('Authorization', `Bearer ${accessToken}`);
    retry.headers.set('X-Retry', '1');
    return fetch(retry);
  },
};

export const api = createClient<paths>({
  baseUrl: ORIGIN,
  // Resolve `fetch` per call so tests can stub `globalThis.fetch` after import.
  fetch: (...args) => globalThis.fetch(...args),
});
api.use(authMiddleware);

export { refreshAccessToken };

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

type ErrorBody = { code?: string; message?: string; detail?: unknown };

/** Narrow an openapi-fetch `{ data, error }` result to `data` or throw. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.data !== undefined) return result.data;
  const body = (result.error ?? {}) as ErrorBody;
  const message =
    body.message ??
    (typeof body.detail === 'string' ? body.detail : null) ??
    `Request failed (${result.response.status})`;
  throw new ApiError(result.response.status, body.code ?? 'error', message);
}
