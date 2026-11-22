import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { SourceDetailPage } from '@/features/sources/SourceDetailPage';
import { setAccessToken } from '@/lib/api/client';

const SOURCE_ID = '11111111-1111-1111-1111-111111111111';
const ONE = '33333333-3333-3333-3333-333333333333';
const TWO = '44444444-4444-4444-4444-444444444444';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function channel(id: string, name: string, hidden: boolean) {
  return {
    id,
    name,
    ext_id: null,
    logo_url: null,
    group_title: 'UK',
    number: null,
    is_hd: false,
    hidden,
    epg_override_id: null,
    programme_count: 10,
  };
}

type Call = { method: string; path: string; search: string; body: unknown };

function renderPage(calls: Call[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (i: RequestInfo | URL, init?: RequestInit) => {
      const req = i instanceof Request ? i : null;
      const href = typeof i === 'string' ? i : i instanceof URL ? i.href : i.url;
      const url = new URL(href, 'http://x');
      const method = (init?.method ?? req?.method ?? 'GET').toUpperCase();
      const raw = method === 'GET' ? '' : ((init?.body as string) ?? (await req!.clone().text()));
      calls.push({ method, path: url.pathname, search: url.search, body: raw && JSON.parse(raw) });
      if (url.pathname === `/api/sources/${SOURCE_ID}`) {
        return json({
          id: SOURCE_ID,
          kind: 'm3u',
          display_name: 'UK',
          enabled: true,
          config_summary: 'http://feed/uk.m3u',
          last_status: 'ok',
          channel_count: 2,
          advertised_epg_urls: [],
          health: 'ok',
        });
      }
      if (url.pathname === `/api/sources/${SOURCE_ID}/channels`) {
        const items = [channel(ONE, 'BBC One', false), channel(TWO, 'BBC Two', true)];
        const q = url.searchParams.get('search');
        const shown = q ? items.filter((c) => c.name.includes(q)) : items;
        return json({ items: shown, total: shown.length, limit: 50, offset: 0 });
      }
      if (url.pathname === `/api/sources/${SOURCE_ID}/channels/visibility`) {
        return json({ updated: 1 });
      }
      if (url.pathname.startsWith('/api/channels/') && method === 'PATCH') {
        return json({ id: ONE, clock_shift_seconds: 0, hidden: true });
      }
      if (url.pathname === '/api/channels/groups') return json(['UK']);
      return json([]);
    }),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[`/sources/${SOURCE_ID}`]}>
        <Routes>
          <Route path="/sources/:sourceId" element={<SourceDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => setAccessToken('test-token'));
afterEach(() => {
  vi.restoreAllMocks();
  setAccessToken(null);
});

test('the In guide tick reflects hidden and unticking hides that channel', async () => {
  const calls: Call[] = [];
  renderPage(calls);
  const one = await screen.findByRole('checkbox', { name: 'Show BBC One in the guide' });
  expect(one).toBeChecked();
  expect(screen.getByRole('checkbox', { name: 'Show BBC Two in the guide' })).not.toBeChecked();
  expect(screen.getByText(/· hidden/)).toBeInTheDocument();

  await userEvent.setup().click(one);
  await waitFor(() =>
    expect(calls).toContainEqual(
      expect.objectContaining({
        method: 'PATCH',
        path: `/api/channels/${ONE}`,
        body: { hidden: true },
      }),
    ),
  );
});

test('the bulk buttons act on the whole source, or on what the filter matches', async () => {
  const calls: Call[] = [];
  renderPage(calls);
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: 'Hide all' }));
  await waitFor(() =>
    expect(calls.filter((c) => c.path.endsWith('/visibility')).map((c) => c.body)).toEqual([
      { hidden: true },
    ]),
  );

  await user.type(screen.getByLabelText('Filter channels'), 'Two');
  await user.click(await screen.findByRole('button', { name: 'Show 1 matching' }));
  await waitFor(() =>
    expect(calls.filter((c) => c.path.endsWith('/visibility')).map((c) => c.body)).toEqual([
      { hidden: true },
      { hidden: false, search: 'Two' },
    ]),
  );
});
