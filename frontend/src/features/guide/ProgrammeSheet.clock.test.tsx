import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { ProgrammeSheet } from '@/features/guide/ProgrammeSheet';
import type { Programme, SearchChannel } from '@/features/guide/api';
import { setAccessToken } from '@/lib/api/client';
import { AuthProvider } from '@/lib/auth/AuthProvider';

/**
 * "On now" and the progress bar came from a bare Date.now() read during
 * render. Nothing re-rendered the sheet on a timer, so the bar froze at
 * whatever it read when the sheet opened, and the badge stayed after the
 * programme had ended. The clock ticks now.
 */

const CHANNEL: SearchChannel = {
  id: '11111111-1111-1111-1111-111111111111',
  name: '70s Cinema',
  number: 401,
  logo_url: null,
  group_title: null,
  is_hd: false,
  timezone: 'UTC',
  clock_shift_seconds: 0,
};

/** Starts an hour ago, runs for two — so it's live and mid-way. */
function programme(now: number): Programme {
  return {
    id: '22222222-2222-2222-2222-222222222222',
    start: new Date(now - 60 * 60_000).toISOString(),
    stop: new Date(now + 60 * 60_000).toISOString(),
    title: 'King Kong',
    sub_title: null,
    description: null,
    categories: ['Film'],
    episode_num: null,
    year: '1976',
    icon_url: null,
    director: null,
    is_movie: true,
    watched: false,
  };
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function widthOfBar(container: HTMLElement): string {
  const bar = container.querySelector('[class*="progress"] > span') as HTMLElement;
  return bar.style.width;
}

beforeEach(() => {
  setAccessToken('t');
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve(json({ code: 'nf' }, 404))),
  );
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
  setAccessToken(null);
});

test('the progress bar advances while the sheet stays open', async () => {
  const start = new Date('2026-09-04T12:00:00Z').getTime();
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.setSystemTime(start);

  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const { container } = render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AuthProvider>
          <ProgrammeSheet
            channel={CHANNEL}
            programme={programme(start)}
            onClose={() => undefined}
          />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );

  const before = widthOfBar(container);
  expect(before).toBe('50%'); // an hour into a two-hour programme

  // Half an hour later, with nothing else touching the component.
  await vi.advanceTimersByTimeAsync(30 * 60_000);
  await waitFor(() => expect(widthOfBar(container)).not.toBe(before));
  expect(widthOfBar(container)).toBe('75%');
});
