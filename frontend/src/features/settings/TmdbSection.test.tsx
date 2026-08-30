import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { TmdbSection } from '@/features/settings/TmdbSection';
import { setAccessToken } from '@/lib/api/client';
import { AuthProvider } from '@/lib/auth/AuthProvider';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function me(over: Record<string, unknown> = {}) {
  return {
    id: 'u',
    email: 'a@b.c',
    display_name: 'A',
    email_verified: true,
    tenant_id: 't',
    default_timezone: 'UTC',
    totp_enabled: false,
    passkey_count: 1,
    tmdb_connected: false,
    ...over,
  };
}

function renderSection() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AuthProvider>
          <TmdbSection />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  setAccessToken('t');
  document.cookie = 'tvtimes_csrf=x';
});

afterEach(() => {
  vi.restoreAllMocks();
  setAccessToken(null);
});

test('connecting a token calls PUT and re-reads /me', async () => {
  let connected = false;
  const fetchMock = vi.fn((i: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof i === 'string' ? i : i instanceof URL ? i.href : i.url;
    const path = new URL(url, 'http://x').pathname;
    const method = init?.method ?? (i instanceof Request ? i.method : 'GET');
    if (path === '/api/auth/refresh') return Promise.resolve(json({ code: 'x' }, 401));
    if (path === '/api/account/me') return Promise.resolve(json(me({ tmdb_connected: connected })));
    if (path === '/api/account/tmdb-token' && method === 'PUT') {
      connected = true;
      return Promise.resolve(json({ message: 'ok' }));
    }
    return Promise.resolve(json({ code: 'nf' }, 404));
  });
  vi.stubGlobal('fetch', fetchMock);

  renderSection();
  const user = userEvent.setup();
  await user.type(screen.getByPlaceholderText(/eyJ/), 'x'.repeat(40));
  await user.click(screen.getByRole('button', { name: 'Connect' }));

  await waitFor(() => expect(screen.getByText('connected')).toBeInTheDocument());
  expect(
    fetchMock.mock.calls.some(([i, init]) => {
      const url = typeof i === 'string' ? i : i instanceof URL ? i.href : i.url;
      const method = init?.method ?? (i instanceof Request ? i.method : 'GET');
      return new URL(url, 'http://x').pathname === '/api/account/tmdb-token' && method === 'PUT';
    }),
  ).toBe(true);
});
