import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { SearchPage } from '@/features/search/SearchPage';
import { setAccessToken } from '@/lib/api/client';
import { AuthProvider } from '@/lib/auth/AuthProvider';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

const HIT = {
  channel: {
    id: 'c1',
    name: 'BBC One',
    number: 1,
    logo_url: null,
    group_title: null,
    is_hd: false,
    timezone: 'Europe/London',
    clock_shift_seconds: 0,
  },
  programme: {
    id: 'p1',
    start: '2026-09-01T20:00:00Z',
    stop: '2026-09-01T22:00:00Z',
    title: 'Blade Runner',
    sub_title: null,
    description: null,
    categories: [],
    episode_num: null,
    year: '1982',
    icon_url: null,
    director: null,
    is_movie: true,
  },
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AuthProvider>
          <SearchPage />
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

test('searching shows hits and a hit opens the programme sheet', async () => {
  const posted: unknown[] = [];
  const fetchMock = vi.fn(async (i: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof i === 'string' ? i : i instanceof URL ? i.href : i.url;
    const { pathname, searchParams } = new URL(url, 'http://x');
    const method = init?.method ?? (i instanceof Request ? i.method : 'GET');
    if (pathname === '/api/watchlist' && method === 'POST') {
      const raw = init?.body ?? (i instanceof Request ? await i.text() : null);
      posted.push(raw ? JSON.parse(raw as string) : null);
      return json({ id: 'w1', kind: 'programme', title: 'Blade Runner', lead_minutes: 15 }, 201);
    }
    if (pathname === '/api/guide/search') {
      expect(searchParams.get('q')).toBe('blade');
      return Promise.resolve(json({ query: 'blade', from: '', to: '', results: [HIT] }));
    }
    if (pathname === '/api/guide/programme/p1/hero') {
      return Promise.resolve(
        json({ tmdb_connected: false, enriching: false, enrichment: null, categories: [] }),
      );
    }
    if (pathname === '/api/auth/refresh') return Promise.resolve(json({ code: 'x' }, 401));
    if (pathname === '/api/account/me') {
      return Promise.resolve(
        json({
          id: 'u',
          email: 'a@b.c',
          display_name: 'A',
          email_verified: true,
          tenant_id: 't',
          default_timezone: 'UTC',
          totp_enabled: false,
          passkey_count: 1,
          tmdb_connected: false,
        }),
      );
    }
    if (pathname === '/api/watchlist') return Promise.resolve(json({ items: [] }, 200));
    return Promise.resolve(json({ code: 'nf' }, 404));
  });
  vi.stubGlobal('fetch', fetchMock);

  renderPage();
  const user = userEvent.setup();
  await user.type(screen.getByPlaceholderText(/title/i), 'blade');

  const row = await screen.findByRole('button', { name: /Blade Runner/ });
  expect(row).toHaveTextContent('BBC One');
  await user.click(row);

  await waitFor(() =>
    expect(screen.getByRole('dialog', { name: 'Blade Runner' })).toBeInTheDocument(),
  );

  await user.click(screen.getByRole('button', { name: 'Remind me' }));
  await waitFor(() =>
    expect(posted).toContainEqual(
      expect.objectContaining({ kind: 'programme', programme_id: 'p1' }),
    ),
  );
});
