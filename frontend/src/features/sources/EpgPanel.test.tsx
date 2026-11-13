import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { EpgPanel } from '@/features/sources/EpgPanel';
import { setAccessToken } from '@/lib/api/client';

const HERE = '11111111-1111-1111-1111-111111111111';
const OTHER = '22222222-2222-2222-2222-222222222222';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function epg(url: string, source_id: string | null, scope_source_id: string | null) {
  return {
    id: crypto.randomUUID(),
    url,
    source_id,
    scope_source_id,
    last_status: 'ok',
    last_error: null,
    programme_count: 1,
    last_fetched_at: null,
    refresh_interval_minutes: 720,
    created_at: new Date().toISOString(),
  };
}

const FEEDS = [
  epg('http://playlist-here/epg.xml', HERE, null),
  epg('http://playlist-other/epg.xml', OTHER, null),
  epg('http://attached-here/epg.xml', null, HERE),
  epg('http://attached-other/epg.xml', null, OTHER),
  epg('http://tenant-wide/epg.xml', null, null),
];

function renderPanel(onAttach: (body: unknown) => void) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (i: RequestInfo | URL, init?: RequestInit) => {
      const req = i instanceof Request ? i : null;
      const method = (init?.method ?? req?.method ?? 'GET').toUpperCase();
      if (method === 'POST') {
        const raw = (init?.body as string | undefined) ?? (await req!.clone().text());
        onAttach(JSON.parse(raw));
        return json(epg('http://new/epg.xml', null, HERE), 201);
      }
      return json(FEEDS);
    }),
  );
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <EpgPanel sourceId={HERE} />
    </QueryClientProvider>,
  );
}

beforeEach(() => setAccessToken('test-token'));
afterEach(() => {
  vi.restoreAllMocks();
  setAccessToken(null);
});

test("lists this source's guides and tenant-wide ones, not another source's", async () => {
  renderPanel(() => undefined);
  expect(await screen.findByText('http://playlist-here/epg.xml')).toBeInTheDocument();
  expect(screen.getByText('http://attached-here/epg.xml')).toBeInTheDocument();
  expect(screen.getByText('http://tenant-wide/epg.xml')).toBeInTheDocument();
  expect(screen.queryByText('http://playlist-other/epg.xml')).not.toBeInTheDocument();
  expect(screen.queryByText('http://attached-other/epg.xml')).not.toBeInTheDocument();
  expect(screen.getByText(/attached here/)).toBeInTheDocument();
  expect(screen.getByText(/attached · all sources/)).toBeInTheDocument();
});

test('attaching a URL scopes it to this source', async () => {
  const bodies: unknown[] = [];
  renderPanel((b) => bodies.push(b));
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText('XMLTV guide URL'), 'http://new/epg.xml');
  await user.click(screen.getByRole('button', { name: 'Attach XMLTV' }));
  await waitFor(() =>
    expect(bodies).toEqual([{ url: 'http://new/epg.xml', scope_source_id: HERE }]),
  );
});
