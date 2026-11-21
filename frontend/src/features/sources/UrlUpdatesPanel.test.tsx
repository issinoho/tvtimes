import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import type { SourceOut } from '@/features/sources/api';
import { UrlUpdatesPanel } from '@/features/sources/UrlUpdatesPanel';
import { curlExample } from '@/features/sources/urlUpdates';
import { setAccessToken } from '@/lib/api/client';

const ID = '11111111-1111-1111-1111-111111111111';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function source(over: Partial<SourceOut> = {}): SourceOut {
  return {
    id: ID,
    kind: 'm3u',
    display_name: 'Pluto',
    enabled: true,
    config_summary: 'http://feed.example.com/a.m3u',
    timezone_override: null,
    clock_shift_seconds: 0,
    refresh_interval_minutes: 360,
    sort_rank: 0,
    last_status: 'ok',
    last_error: null,
    channel_count: 1,
    epg_url: null,
    advertised_epg_urls: [],
    last_refreshed_at: null,
    created_at: new Date().toISOString(),
    health: 'ok',
    epg_status: null,
    epg_error: null,
    epg_last_fetched_at: null,
    programme_count: 0,
    url_updates_supported: true,
    update_token_set_at: null,
    update_token_last_used_at: null,
    ...over,
  };
}

function renderPanel(s: SourceOut) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <UrlUpdatesPanel source={s} />
    </QueryClientProvider>,
  );
}

beforeEach(() => setAccessToken('test-token'));
afterEach(() => {
  vi.restoreAllMocks();
  setAccessToken(null);
});

test('hidden for a source kind with no URL to push', () => {
  const { container } = renderPanel(source({ kind: 'hdhomerun', url_updates_supported: false }));
  expect(container).toBeEmptyDOMElement();
});

test('creating a token shows it once inside a ready-to-run curl command', async () => {
  const calls: string[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn((i: RequestInfo | URL, init?: RequestInit) => {
      const req = i instanceof Request ? i : null;
      const url = i instanceof Request ? i.url : i.toString();
      calls.push(`${(init?.method ?? req?.method ?? 'GET').toUpperCase()} ${url}`);
      return Promise.resolve(json({ token: 'tok-123', set_at: new Date().toISOString() }, 201));
    }),
  );
  renderPanel(source());

  await userEvent.click(screen.getByRole('button', { name: 'Create update token' }));
  expect(await screen.findByText(/Bearer tok-123/)).toBeInTheDocument();
  expect(calls.some((c) => c.startsWith('POST') && c.endsWith(`/sources/${ID}/update-token`))).toBe(
    true,
  );
});

test('an enabled source offers rotate and turn off, without the token', () => {
  renderPanel(source({ update_token_set_at: new Date().toISOString() }));
  expect(screen.getByRole('button', { name: 'Rotate token' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Turn off' })).toBeInTheDocument();
  expect(screen.getByText(/Bearer <token>/)).toBeInTheDocument();
});

test('the curl example targets the hook with a bearer header', () => {
  const cmd = curlExample('https://tv.example.com', 'abc');
  expect(cmd).toContain('POST https://tv.example.com/api/hooks/source-url');
  expect(cmd).toContain("Authorization: Bearer abc'");
});
