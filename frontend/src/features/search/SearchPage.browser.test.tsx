import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { SearchPage } from '@/features/search/SearchPage';
import { setAccessToken } from '@/lib/api/client';
import '@/styles/global.css';

/**
 * A result row's title and channel are separate spans. Their container was
 * never made a flex column, so they ran together on one line —
 * "King Kong · 197670s Cinema" — and a long title overflowed the row instead
 * of truncating, because text-overflow needs a block box.
 *
 * jsdom can't see either: it has no box model, so both spans report the same
 * empty geometry whichever way the CSS goes.
 */

const LONG_TITLE = "2026 WBSC Women's Baseball World Cup - Group Stage Match 12";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function pathOf(i: RequestInfo | URL): string {
  const url = typeof i === 'string' ? i : i instanceof URL ? i.href : i.url;
  return new URL(url, 'http://x').pathname;
}

function hit(id: string, title: string, channel: string) {
  return {
    channel: {
      id,
      name: channel,
      number: 1,
      logo_url: null,
      group_title: null,
      is_hd: false,
      timezone: 'Europe/London',
      clock_shift_seconds: 0,
    },
    programme: {
      id: `p-${id}`,
      start: '2026-09-04T20:00:00Z',
      stop: '2026-09-04T22:00:00Z',
      title,
      sub_title: null,
      description: null,
      categories: [],
      episode_num: null,
      year: null,
      icon_url: null,
      director: null,
      is_movie: false,
      watched: false,
    },
  };
}

function renderResults() {
  vi.stubGlobal(
    'fetch',
    vi.fn((i: RequestInfo | URL) => {
      const path = pathOf(i);
      if (path === '/api/auth/refresh') return Promise.resolve(json({ code: 'x' }, 401));
      if (path === '/api/guide/search') {
        return Promise.resolve(
          json({
            results: [
              hit('11111111-1111-1111-1111-111111111111', 'King Kong', '70s Cinema'),
              hit('22222222-2222-2222-2222-222222222222', LONG_TITLE, 'AWSN'),
            ],
          }),
        );
      }
      return Promise.resolve(json({ code: 'nf' }, 404));
    }),
  );

  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/search?q=kong']}>
        <Routes>
          <Route path="/search" element={<SearchPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => setAccessToken('t'));
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  setAccessToken(null);
});

test('a result row puts the channel on its own line below the title', async () => {
  renderResults();
  const title = await screen.findByText(/King Kong/);
  const meta = screen.getByText(/70s Cinema/);

  const t = title.getBoundingClientRect();
  const m = meta.getBoundingClientRect();

  // Stacked, not inline: the channel starts at or below where the title ends.
  expect(m.top).toBeGreaterThanOrEqual(t.bottom - 1);
  // And they share a left edge, rather than the channel trailing the title.
  expect(m.left).toBeCloseTo(t.left, 0);
});

test('a long title is truncated rather than overflowing the row', async () => {
  renderResults();
  const title = await screen.findByText(new RegExp(LONG_TITLE.slice(0, 20)));
  const row = title.closest('button') as HTMLElement;

  // The row must not be forced wider than the list it sits in.
  expect(row.scrollWidth).toBeLessThanOrEqual(row.clientWidth + 1);
  // The title itself is clipped, which is what ellipsis does.
  expect(title.scrollWidth).toBeGreaterThan(title.clientWidth);
});
