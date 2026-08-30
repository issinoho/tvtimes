import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { setAccessToken } from '@/lib/api/client';
import { SourcesPage } from '@/features/sources/SourcesPage';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

/** openapi-fetch calls `fetch(request)` with a Request object and no init. */
function reqInfo(i: RequestInfo | URL, init?: RequestInit): { path: string; method: string } {
  const url = typeof i === 'string' ? i : i instanceof URL ? i.href : i.url;
  const method = init?.method ?? (i instanceof Request ? i.method : 'GET');
  return { path: new URL(url, 'http://x').pathname, method: method.toUpperCase() };
}

const M3U_SOURCE = {
  id: '11111111-1111-1111-1111-111111111111',
  kind: 'm3u',
  display_name: 'My playlist',
  enabled: true,
  config_summary: 'http://feed.example.com/list.m3u',
  timezone_override: null,
  clock_shift_seconds: 0,
  refresh_interval_minutes: 360,
  last_status: 'ok',
  last_error: null,
  channel_count: 42,
  epg_url: null,
  last_refreshed_at: null,
  created_at: new Date().toISOString(),
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/sources']}>
        <Routes>
          <Route path="/sources" element={<SourcesPage />} />
          <Route path="/sources/:id" element={<div>detail</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  setAccessToken('test-token');
});

afterEach(() => {
  vi.restoreAllMocks();
  setAccessToken(null);
});

test('lists sources with status and channel count', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn((i: RequestInfo | URL, init?: RequestInit) => {
      const { path } = reqInfo(i, init);
      return Promise.resolve(
        path === '/api/sources' ? json([M3U_SOURCE]) : json({ code: 'not_found' }, 404),
      );
    }),
  );
  renderPage();
  await waitFor(() => expect(screen.getByText('My playlist')).toBeInTheDocument());
  expect(screen.getByText(/42 channels/)).toBeInTheDocument();
  expect(screen.getByText('Ready')).toBeInTheDocument();
});

test('the add-source dialog posts a new m3u source', async () => {
  const fetchMock = vi.fn((i: RequestInfo | URL, init?: RequestInit) => {
    const { path, method } = reqInfo(i, init);
    if (path === '/api/sources' && method === 'POST') return Promise.resolve(json(M3U_SOURCE, 201));
    if (path === '/api/sources') return Promise.resolve(json([]));
    return Promise.resolve(json({ code: 'not_found' }, 404));
  });
  vi.stubGlobal('fetch', fetchMock);

  renderPage();
  const user = userEvent.setup();
  await user.click(await screen.findByRole('button', { name: /add source/i }));
  const dialog = within(screen.getByRole('dialog'));
  await user.type(dialog.getByLabelText('Name'), 'Living room');
  await user.type(dialog.getByLabelText('Playlist URL'), 'http://feed.example.com/list.m3u');
  await user.click(dialog.getByRole('button', { name: /add source/i }));

  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(([i, init]) => {
        const { path, method } = reqInfo(i, init);
        return path === '/api/sources' && method === 'POST';
      }),
    ).toBe(true),
  );
});
