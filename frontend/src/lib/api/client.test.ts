import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { refreshAccessToken } from './client';

function jsonOk(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

beforeEach(() => {
  document.cookie = 'tvtimes_csrf=x';
});

afterEach(() => {
  vi.restoreAllMocks();
});

test('concurrent refreshes collapse into a single request', async () => {
  let calls = 0;
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => {
      calls += 1;
      await new Promise((r) => setTimeout(r, 10));
      return jsonOk({ access_token: 't' });
    }),
  );

  const results = await Promise.all([
    refreshAccessToken(),
    refreshAccessToken(),
    refreshAccessToken(),
  ]);

  expect(results).toEqual([true, true, true]);
  expect(calls).toBe(1); // not a burst that would rotate the token against itself
});

test('a later refresh, after the first settles, makes its own request', async () => {
  const fetchMock = vi.fn(() => Promise.resolve(jsonOk({ access_token: 't' })));
  vi.stubGlobal('fetch', fetchMock);

  await refreshAccessToken();
  await refreshAccessToken();

  expect(fetchMock).toHaveBeenCalledTimes(2);
});
