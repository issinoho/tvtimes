import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { ExportsSection } from '@/features/settings/ExportsSection';
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
    export_token_set_at: null,
    ...over,
  };
}

function pathOf(i: RequestInfo | URL): string {
  const url = typeof i === 'string' ? i : i instanceof URL ? i.href : i.url;
  return new URL(url, 'http://x').pathname;
}
function methodOf(i: RequestInfo | URL, init?: RequestInit): string {
  return init?.method ?? (i instanceof Request ? i.method : 'GET');
}

function renderSection(playlistUrl: string) {
  const fetchMock = vi.fn((i: RequestInfo | URL, init?: RequestInit) => {
    const path = pathOf(i);
    if (path === '/api/auth/refresh') return Promise.resolve(json({ code: 'x' }, 401));
    if (path === '/api/account/me') return Promise.resolve(json(me()));
    if (path === '/api/account/export-token' && methodOf(i, init) === 'POST') {
      return Promise.resolve(
        json({
          token: 'abc',
          playlist_url: playlistUrl,
          epg_url: playlistUrl.replace('playlist.m3u', 'epg.xml'),
        }),
      );
    }
    return Promise.resolve(json({ code: 'nf' }, 404));
  });
  vi.stubGlobal('fetch', fetchMock);

  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AuthProvider>
          <ExportsSection />
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

test('offers the generated feeds as a tvtimess:// link for tvdinner', async () => {
  renderSection('https://tv.example.com/api/exports/playlist.m3u?token=abc');
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: 'Generate feed links' }));

  const link = await screen.findByRole('link', { name: 'Open in tvdinner' });
  expect(link).toHaveAttribute('href', 'tvtimess://tv.example.com?token=abc');
});

test('uses the plain tvtimes:// scheme for a http deployment, keeping any base path', async () => {
  renderSection('http://192.168.1.5:8888/tv/api/exports/playlist.m3u?token=abc');
  const user = userEvent.setup();
  await user.click(screen.getByRole('button', { name: 'Generate feed links' }));

  await waitFor(() =>
    expect(screen.getByRole('link', { name: 'Open in tvdinner' })).toHaveAttribute(
      'href',
      'tvtimes://192.168.1.5:8888/tv?token=abc',
    ),
  );
});
