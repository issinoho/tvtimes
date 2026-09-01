import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { FavStar } from '@/features/favourites/FavStar';
import { setAccessToken } from '@/lib/api/client';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function renderStar(channelId = 'c1') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <FavStar channelId={channelId} />
    </QueryClientProvider>,
  );
}

beforeEach(() => setAccessToken('t'));
afterEach(() => {
  vi.restoreAllMocks();
  setAccessToken(null);
});

test('toggling the star POSTs then DELETEs the favourite', async () => {
  const favs = new Set<string>();
  const seen: { method: string; path: string }[] = [];
  const fetchMock = vi.fn((i: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof i === 'string' ? i : i instanceof URL ? i.href : i.url;
    const { pathname } = new URL(url, 'http://x');
    const method = init?.method ?? (i instanceof Request ? i.method : 'GET');
    seen.push({ method, path: pathname });
    if (pathname === '/api/favourites' && method === 'GET') {
      return Promise.resolve(json({ channel_ids: [...favs] }));
    }
    if (pathname === '/api/favourites' && method === 'POST') {
      favs.add('c1');
      return Promise.resolve(json({ message: 'ok' }, 201));
    }
    if (pathname === '/api/favourites/c1' && method === 'DELETE') {
      favs.delete('c1');
      return Promise.resolve(json({ message: 'ok' }));
    }
    return Promise.resolve(json({ code: 'nf' }, 404));
  });
  vi.stubGlobal('fetch', fetchMock);

  renderStar();
  const user = userEvent.setup();

  const btn = await screen.findByRole('button', { name: /add channel to favourites/i });
  await user.click(btn);

  await waitFor(() =>
    expect(seen.some((r) => r.method === 'POST' && r.path === '/api/favourites')).toBe(true),
  );
  // optimistic flip
  expect(
    await screen.findByRole('button', { name: /remove channel from favourites/i }),
  ).toHaveTextContent('★');

  await user.click(screen.getByRole('button', { name: /remove channel from favourites/i }));
  await waitFor(() =>
    expect(seen.some((r) => r.method === 'DELETE' && r.path === '/api/favourites/c1')).toBe(true),
  );
});
