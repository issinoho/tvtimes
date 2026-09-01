import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi, type Mock } from 'vitest';

import { PlayControls } from '@/features/guide/ProgrammeSheet';
import { setAccessToken } from '@/lib/api/client';
import { isAndroid } from '@/lib/platform';

vi.mock('@/lib/platform', () => ({ isAndroid: vi.fn(() => false) }));

// jsdom makes window.location.assign non-configurable, so swap the whole object.
const realLocation = window.location;
let assign: Mock;

const LINK = {
  m3u_url: 'https://x/api/exports/play/ch1/playlist.m3u?ticket=T',
  stream_url: 'https://x/api/exports/play/ch1/stream?ticket=T',
  expires_in: 86400,
};

const CHANNEL = {
  id: 'ch1',
  name: 'BBC One',
  number: 1,
  logo_url: null,
  group_title: null,
  is_hd: false,
  timezone: 'UTC',
  clock_shift_seconds: 0,
};

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
function methodOf(i: RequestInfo | URL, init?: RequestInit): string {
  return init?.method ?? (i instanceof Request ? i.method : 'GET');
}

function mountPlay(
  mint: (i: RequestInfo | URL, init?: RequestInit) => Promise<Response> = () =>
    Promise.resolve(json(LINK)),
) {
  const calls: string[] = [];
  const fetchMock = vi.fn((i: RequestInfo | URL, init?: RequestInit) => {
    const path = pathOf(i);
    const method = methodOf(i, init);
    calls.push(`${method} ${path}`);
    if (path === '/api/auth/refresh') return Promise.resolve(json({ code: 'x' }, 401));
    if (path === '/api/channels/ch1/play-link' && method === 'POST') return mint(i, init);
    return Promise.resolve(json({ code: 'nf' }, 404));
  });
  vi.stubGlobal('fetch', fetchMock);
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={qc}>
      <PlayControls channel={CHANNEL} />
    </QueryClientProvider>,
  );
  return calls;
}

beforeEach(() => {
  setAccessToken('t');
  document.cookie = 'tvtimes_csrf=x';
  vi.mocked(isAndroid).mockReturnValue(false);
  assign = vi.fn();
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: { ...realLocation, assign },
  });
});
afterEach(() => {
  Object.defineProperty(window, 'location', { configurable: true, value: realLocation });
  vi.restoreAllMocks();
  setAccessToken(null);
});

test('does not mint a link on mount', () => {
  const calls = mountPlay();
  expect(calls.some((c) => c.includes('/play-link'))).toBe(false);
});

test('desktop: Play hands off with a tvdinner: link', async () => {
  mountPlay();
  await userEvent.setup().click(screen.getByRole('button', { name: 'Play' }));
  await waitFor(() => expect(assign).toHaveBeenCalledWith(`tvdinner:${LINK.m3u_url}`));
  expect(assign).toHaveBeenCalledTimes(1);
});

test('desktop: Download .m3u navigates to the raw playlist url', async () => {
  mountPlay();
  await userEvent.setup().click(screen.getByRole('button', { name: 'Download .m3u' }));
  await waitFor(() => expect(assign).toHaveBeenCalledWith(LINK.m3u_url));
  expect(assign).toHaveBeenCalledTimes(1);
});

test('android: Play fires an intent:// url with a .m3u fallback', async () => {
  vi.mocked(isAndroid).mockReturnValue(true);
  mountPlay();
  await userEvent.setup().click(screen.getByRole('button', { name: 'Play' }));
  await waitFor(() => expect(assign).toHaveBeenCalled());
  const arg = assign.mock.calls[0][0] as string;
  expect(
    arg.startsWith('intent://x/api/exports/play/ch1/stream?ticket=T#Intent;scheme=https;'),
  ).toBe(true);
  expect(arg).toContain('type=video/*');
  expect(arg).toContain(`S.browser_fallback_url=${encodeURIComponent(LINK.m3u_url)}`);
  expect(arg.endsWith(';end')).toBe(true);
});

test('Copy stream URL copies the stream url and flashes', async () => {
  const user = userEvent.setup(); // installs a clipboard stub we read back
  mountPlay();
  await user.click(screen.getByRole('button', { name: 'Copy stream URL' }));
  await waitFor(async () => expect(await navigator.clipboard.readText()).toBe(LINK.stream_url));
  expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument();
});

test('a 501 from the mint shows an inline message and does not navigate', async () => {
  mountPlay(() => Promise.resolve(json({ message: 'Stalker portal…' }, 501)));
  await userEvent.setup().click(screen.getByRole('button', { name: 'Play' }));
  await waitFor(() =>
    expect(screen.getByText('Not available for this source.')).toBeInTheDocument(),
  );
  expect(assign).not.toHaveBeenCalled();
});
