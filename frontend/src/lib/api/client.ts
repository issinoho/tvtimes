/**
 * Minimal API client for phase 1.
 *
 * Phase 2 swaps this for `openapi-fetch` typed against `schema.d.ts`, which is
 * generated from the live OpenAPI document with `npm run gen:api`.
 */

const API_BASE = (import.meta.env.VITE_API_BASE ?? '/api').replace(/\/$/, '');

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

export async function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { Accept: 'application/json', ...init?.headers },
    credentials: 'include',
  });
  if (!res.ok) {
    throw new ApiError(res.status, `GET ${path} -> ${res.status}`);
  }
  return (await res.json()) as T;
}

export interface Health {
  status: 'ok';
  version: string;
}

export const getHealth = (): Promise<Health> => apiGet<Health>('/healthz');
