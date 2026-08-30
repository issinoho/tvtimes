import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { GuidePage } from '@/features/guide/GuidePage';
import { setAccessToken } from '@/lib/api/client';
import { AuthProvider } from '@/lib/auth/AuthProvider';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

const NOW = new Date();
const prog = (offsetMin: number, durMin: number, over: Record<string, unknown> = {}) => ({
  id: `p-${offsetMin}`,
  start: new Date(NOW.getTime() + offsetMin * 60_000).toISOString(),
  stop: new Date(NOW.getTime() + (offsetMin + durMin) * 60_000).toISOString(),
  title: `Show ${offsetMin}`,
  sub_title: null,
  description: 'A thing happens.',
  categories: ['News'],
  episode_num: null,
  year: null,
  icon_url: null,
  director: null,
  is_movie: false,
  ...over,
});

const GUIDE = {
  from: NOW.toISOString(),
  to: NOW.toISOString(),
  channels: [
    {
      id: 'c1',
      name: 'News HD',
      number: 101,
      logo_url: null,
      group_title: 'News',
      is_hd: true,
      timezone: 'UTC',
      programmes: [
        prog(-30, 60),
        prog(30, 60, { title: 'The Big Film', is_movie: true, year: '1999' }),
      ],
    },
  ],
};

function mockFetch() {
  vi.stubGlobal(
    'fetch',
    vi.fn((i: RequestInfo | URL) => {
      const url = typeof i === 'string' ? i : i instanceof URL ? i.href : i.url;
      const path = new URL(url, 'http://x').pathname;
      if (path === '/api/auth/refresh') return Promise.resolve(json({ code: 'x' }, 401));
      if (path === '/api/account/me')
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
      if (path === '/api/sources') return Promise.resolve(json([]));
      if (path === '/api/guide') return Promise.resolve(json(GUIDE));
      if (path.startsWith('/api/guide/programme/'))
        return Promise.resolve(
          json({
            programme_id: 'p1',
            channel_name: 'News HD',
            title: 'The Big Film',
            sub_title: null,
            start: NOW.toISOString(),
            stop: NOW.toISOString(),
            description: 'A thing happens.',
            categories: ['News'],
            episode_num: null,
            year: '1999',
            is_movie: true,
            tmdb_connected: false,
            enriching: false,
            enrichment: null,
          }),
        );
      return Promise.resolve(json({ code: 'nf' }, 404));
    }),
  );
}

function renderGuide() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AuthProvider>
          <GuidePage />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  setAccessToken('t');
  document.cookie = 'tvtimes_csrf=x';
  mockFetch();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  setAccessToken(null);
});

test('desktop: toolbar renders and the group filter is populated from the guide', async () => {
  renderGuide();
  await waitFor(() => expect(screen.getByRole('button', { name: 'Now' })).toBeInTheDocument());
  const groupSelect = screen.getByLabelText('Group');
  await waitFor(() =>
    expect(within(groupSelect).getByRole('option', { name: 'News' })).toBeInTheDocument(),
  );
});

test('desktop: searching for a missing channel shows the empty message', async () => {
  renderGuide();
  const user = userEvent.setup();
  await waitFor(() => expect(screen.getByRole('button', { name: 'Now' })).toBeInTheDocument());
  await user.type(screen.getByPlaceholderText(/find a channel/i), 'sport');
  await waitFor(() => expect(screen.getByText(/No channels match/)).toBeInTheDocument());
});

test('mobile: the agenda lists programmes and a tap opens the detail sheet', async () => {
  vi.stubGlobal(
    'matchMedia',
    vi.fn((q: string) => ({
      matches: q.includes('max-width'),
      media: q,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      onchange: null,
      dispatchEvent: vi.fn(),
    })),
  );

  renderGuide();
  const user = userEvent.setup();
  await waitFor(() => expect(screen.getByText('The Big Film')).toBeInTheDocument());
  await user.click(screen.getByText('The Big Film'));

  const dialog = await screen.findByRole('dialog', { name: 'The Big Film' });
  const sheet = within(dialog);
  expect(sheet.getByText('A thing happens.')).toBeInTheDocument();
  expect(sheet.getByText('1999', { exact: false })).toBeInTheDocument();
  // focus moved into the dialog on open
  expect(dialog.contains(document.activeElement)).toBe(true);
});
