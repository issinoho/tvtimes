import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { SourceDetailPage } from '@/features/sources/SourceDetailPage';
import { setAccessToken } from '@/lib/api/client';

const SOURCE_ID = '11111111-1111-1111-1111-111111111111';
const HD_ID = '22222222-2222-2222-2222-222222222222';

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

// The real case: the tuner numbers this 101, the guide carries the same
// programming under 1, so nothing matches and the row is empty.
const CHANNELS = [
  {
    id: '33333333-3333-3333-3333-333333333333',
    name: 'BBC ONE Scot',
    ext_id: '1',
    logo_url: null,
    group_title: null,
    number: 1,
    is_hd: false,
    epg_override_id: null,
    programme_count: 71,
  },
  {
    id: HD_ID,
    name: 'BBC 1 Scot HD',
    ext_id: '101',
    logo_url: null,
    group_title: null,
    number: 101,
    is_hd: true,
    epg_override_id: null,
    programme_count: 0,
  },
];

function renderPage(onPatch: (body: unknown) => void) {
  const fetchMock = vi.fn(async (i: RequestInfo | URL, init?: RequestInit) => {
    const path = pathOf(i);
    const method = init?.method ?? (i instanceof Request ? i.method : 'GET');
    if (path === `/api/sources/${SOURCE_ID}`) {
      return json({
        id: SOURCE_ID,
        kind: 'hdhomerun',
        display_name: 'HDHomeRun',
        enabled: true,
        config_summary: 'http://192.168.0.11',
        timezone_override: null,
        clock_shift_seconds: 0,
        refresh_interval_minutes: 360,
        last_status: 'ok',
        last_error: null,
        channel_count: 2,
        epg_url: null,
        last_refreshed_at: null,
        created_at: new Date().toISOString(),
        health: 'ok',
        epg_status: 'ok',
        epg_error: null,
        epg_last_fetched_at: null,
        programme_count: 71,
      });
    }
    if (path === `/api/sources/${SOURCE_ID}/channels`) {
      return json({ items: CHANNELS, total: 2, limit: 50, offset: 0 });
    }
    if (path === `/api/channels/${HD_ID}` && method.toUpperCase() === 'PATCH') {
      // openapi-fetch passes a Request with no init, so the body may be on
      // either; both are strings here.
      const raw = (init?.body as string | undefined) ?? (await (i as Request).clone().text());
      onPatch(JSON.parse(raw));
      return json({ id: HD_ID, clock_shift_seconds: 0, epg_override_id: '1' });
    }
    return json({ code: 'nf' }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);

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

test('a channel with no guide data is called out in the channel list', async () => {
  renderPage(() => undefined);
  // "none" is the whole point: an empty guide row is otherwise invisible
  // until you go looking at the grid.
  expect(await screen.findByText('none')).toBeInTheDocument();
  expect(screen.getByText('71')).toBeInTheDocument();
});

test('typing a guide key against that channel saves it', async () => {
  const bodies: unknown[] = [];
  renderPage((b) => bodies.push(b));
  const user = userEvent.setup();

  const field = await screen.findByLabelText('Guide key for BBC 1 Scot HD');
  await user.type(field, '1');
  await user.tab();

  await waitFor(() => expect(bodies).toEqual([{ epg_override_id: '1' }]));
});

test('leaving a guide key untouched saves nothing', async () => {
  const bodies: unknown[] = [];
  renderPage((b) => bodies.push(b));
  const user = userEvent.setup();

  const field = await screen.findByLabelText('Guide key for BBC 1 Scot HD');
  await user.click(field);
  await user.tab();

  expect(bodies).toEqual([]);
});
