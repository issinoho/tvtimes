import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { EditSourceDialog } from '@/features/sources/EditSourceDialog';
import type { SourceOut } from '@/features/sources/api';
import { setAccessToken } from '@/lib/api/client';

function source(over: Partial<SourceOut>): SourceOut {
  return {
    id: '11111111-1111-1111-1111-111111111111',
    kind: 'm3u',
    display_name: 'Pluto',
    enabled: true,
    config_summary: 'http://feed.example.com/list.m3u',
    timezone_override: null,
    clock_shift_seconds: 0,
    refresh_interval_minutes: 360,
    sort_rank: 0,
    last_status: 'ok',
    last_error: null,
    channel_count: 1,
    epg_url: null,
    last_refreshed_at: null,
    created_at: new Date().toISOString(),
    health: 'ok',
    epg_status: null,
    epg_error: null,
    epg_last_fetched_at: null,
    programme_count: 0,
    ...over,
  };
}

function setup(src: SourceOut) {
  const bodies: unknown[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (i: RequestInfo | URL, init?: RequestInit) => {
      const req = i instanceof Request ? i : null;
      const raw = (init?.body as string | undefined) ?? (req ? await req.clone().text() : '');
      if (raw) bodies.push(JSON.parse(raw));
      return new Response(JSON.stringify(src), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    }),
  );
  const onClose = vi.fn();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <EditSourceDialog source={src} onClose={onClose} />
    </QueryClientProvider>,
  );
  return { bodies, onClose, user: userEvent.setup() };
}

beforeEach(() => setAccessToken('test-token'));
afterEach(() => {
  vi.restoreAllMocks();
  setAccessToken(null);
});

test('sends only what changed, and a new playlist URL as its connection', async () => {
  const { bodies, onClose, user } = setup(source({}));
  await user.type(screen.getByLabelText('Playlist URL'), 'http://feed.example.com/new.m3u');
  await user.selectOptions(screen.getByLabelText('Refresh channels'), '720');
  await user.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() => expect(onClose).toHaveBeenCalled());
  expect(bodies).toEqual([
    {
      refresh_interval_minutes: 720,
      config: { kind: 'm3u', url: 'http://feed.example.com/new.m3u' },
    },
  ]);
});

test('blank Xtream fields keep the stored credentials', async () => {
  const { bodies, onClose, user } = setup(
    source({ kind: 'xtream', config_summary: 'al***@panel.example.com' }),
  );
  await user.type(screen.getByLabelText('Server URL'), 'http://new-panel.example.com');
  await user.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() => expect(onClose).toHaveBeenCalled());
  expect(bodies).toEqual([
    { config: { kind: 'xtream', server_url: 'http://new-panel.example.com' } },
  ]);
});

test('saving with nothing changed makes no request', async () => {
  const { bodies, onClose, user } = setup(source({}));
  await user.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() => expect(onClose).toHaveBeenCalled());
  expect(bodies).toEqual([]);
});

test('an HDHomeRun address starts filled in and can be cleared to auto-discover', async () => {
  const { bodies, onClose, user } = setup(
    source({ kind: 'hdhomerun', config_summary: 'http://192.168.1.50' }),
  );
  const field = screen.getByLabelText('Device address (optional)');
  expect(field).toHaveValue('http://192.168.1.50');
  await user.clear(field);
  await user.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() => expect(onClose).toHaveBeenCalled());
  expect(bodies).toEqual([{ config: { kind: 'hdhomerun', device_url: '' } }]);
});
