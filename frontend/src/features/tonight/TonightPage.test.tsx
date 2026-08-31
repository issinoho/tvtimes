import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { TonightPage } from '@/features/tonight/TonightPage';
import { setAccessToken } from '@/lib/api/client';
import { AuthProvider } from '@/lib/auth/AuthProvider';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

const CHANNEL = {
  id: 'c1',
  name: 'BBC One',
  number: 1,
  logo_url: null,
  group_title: null,
  is_hd: false,
  timezone: 'Europe/London',
  clock_shift_seconds: 0,
};

function programme(id: string, title: string) {
  return {
    id,
    start: '2026-09-01T20:00:00Z',
    stop: '2026-09-01T22:00:00Z',
    title,
    sub_title: null,
    description: null,
    categories: [],
    episode_num: null,
    year: '1999',
    icon_url: null,
    director: null,
    is_movie: true,
  };
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AuthProvider>
          <TonightPage />
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

test('renders on-now and highlights, and a card opens the sheet', async () => {
  const fetchMock = vi.fn((i: RequestInfo | URL) => {
    const url = typeof i === 'string' ? i : i instanceof URL ? i.href : i.url;
    const { pathname } = new URL(url, 'http://x');
    if (pathname === '/api/guide/now-next') {
      return Promise.resolve(
        json({
          now: '2026-09-01T20:30:00Z',
          channels: [
            {
              channel: CHANNEL,
              current: programme('p-now', 'The Matrix'),
              upcoming: programme('p-next', 'Blade Runner'),
            },
          ],
        }),
      );
    }
    if (pathname === '/api/guide/highlights') {
      return Promise.resolve(
        json({
          films_soon: [{ channel: CHANNEL, programme: programme('p-soon', 'Heat') }],
          top_rated: [{ channel: CHANNEL, programme: programme('p-top', 'Goodfellas') }],
        }),
      );
    }
    if (pathname === '/api/guide/programme/p-now/hero') {
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
    if (pathname === '/api/watchlist') return Promise.resolve(json({ items: [] }));
    return Promise.resolve(json({ code: 'nf' }, 404));
  });
  vi.stubGlobal('fetch', fetchMock);

  renderPage();
  const user = userEvent.setup();

  const nowCard = await screen.findByRole('button', { name: /The Matrix/ });
  expect(nowCard).toHaveTextContent('Blade Runner'); // "Next: …"
  expect(await screen.findByText('Films on soon')).toBeInTheDocument();
  expect(screen.getByText('Top rated this week')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /Goodfellas/ })).toHaveTextContent('#1');

  await user.click(nowCard);
  await waitFor(() =>
    expect(screen.getByRole('dialog', { name: 'The Matrix' })).toBeInTheDocument(),
  );
});
