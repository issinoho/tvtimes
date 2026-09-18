import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import type { GuideChannel } from '@/features/guide/api';
import { GuideGrid } from '@/features/guide/GuideGrid';
import { ROW_H } from '@/features/guide/time';
import '@/styles/global.css';

/**
 * The ▲/▼ buttons exist so Silk on a Fire TV Stick, whose remote drives a
 * cursor that can only scroll the document, can reach channels past the first
 * screenful (see GuideGrid.tsx). Whether a press actually moves the grid is a
 * question about scroll position and the box model, neither of which jsdom
 * has.
 */

const START = new Date('2026-09-05T12:00:00Z');

function channels(count: number): GuideChannel[] {
  return Array.from({ length: count }, (_, i) => ({
    id: `c${i}`,
    name: `Channel ${i}`,
    number: 100 + i,
    logo_url: null,
    group_title: null,
    is_hd: false,
    timezone: 'UTC',
    clock_shift_seconds: 0,
    programmes: [
      {
        id: `p${i}`,
        start: START.toISOString(),
        stop: new Date(START.getTime() + 3_600_000).toISOString(),
        title: `Show ${i}`,
        sub_title: null,
        description: null,
        categories: [],
        episode_num: null,
        year: null,
        icon_url: null,
        director: null,
        is_movie: false,
        watched: false,
      },
    ],
  }));
}

function Grid({ count }: { count: number }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      {/* The guide page is a flex column the grid fills; give it a TV-ish box. */}
      <div style={{ display: 'flex', flexDirection: 'column', width: 900, height: 500 }}>
        <GuideGrid channels={channels(count)} windowStart={START} onOpen={() => undefined} />
      </div>
    </QueryClientProvider>
  );
}

const up = () => screen.getByRole('button', { name: 'Previous channels' });
const down = () => screen.getByRole('button', { name: 'More channels' });
const body = () => screen.getByRole('grid', { name: 'TV guide' });

/** Wait for a smooth scroll to finish: pressing again mid-flight loses the
 *  remainder of the one still animating. */
async function settled(el: HTMLElement) {
  let previous = -1;
  await expect
    .poll(() => {
      const here = el.scrollTop;
      const stopped = here === previous;
      previous = here;
      return stopped;
    })
    .toBe(true);
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve(new Response('{}', { status: 404 }))),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

test('▼ pages down by whole rows, and ▲ comes back to the top', async () => {
  render(<Grid count={60} />);
  await expect.poll(() => screen.queryAllByRole('button', { name: /channels$/ })).toHaveLength(2);
  const el = body();

  expect(el.scrollHeight).toBeGreaterThan(el.clientHeight); // the premise
  expect(up()).toHaveAttribute('aria-disabled', 'true');
  expect(down()).toHaveAttribute('aria-disabled', 'false');
  // Dimmed, but never `disabled` -- that would drop focus.
  expect((up() as HTMLButtonElement).disabled).toBe(false);

  down().click();
  await settled(el);
  expect(el.scrollTop).toBeGreaterThan(0);
  // Nearly a screenful, not the whole list, and on a row boundary.
  expect(el.scrollTop).toBeLessThan(el.clientHeight);
  expect(el.scrollTop % ROW_H).toBe(0);
  await expect.poll(() => up().getAttribute('aria-disabled')).toBe('false');

  // The channel column follows the programmes.
  const chan = screen.getByText('Channel 0').closest('div')?.parentElement?.parentElement;
  expect(chan?.scrollTop).toBe(el.scrollTop);

  up().click();
  await expect.poll(() => el.scrollTop).toBe(0);
  await expect.poll(() => up().getAttribute('aria-disabled')).toBe('true');
});

test('walking down reaches the last channel and stops there', async () => {
  render(<Grid count={60} />);
  await expect.poll(() => screen.queryAllByRole('button', { name: /channels$/ })).toHaveLength(2);
  const el = body();

  for (let i = 0; i < 20 && down().getAttribute('aria-disabled') === 'false'; i++) {
    down().click();
    await settled(el);
  }

  await expect.poll(() => down().getAttribute('aria-disabled')).toBe('true');
  expect(el.scrollTop).toBeGreaterThan(el.scrollHeight - el.clientHeight - 2);
  expect(screen.getByText('Channel 59')).toBeVisible();
});

test('a guide short enough to fit shows no buttons at all', async () => {
  render(<Grid count={3} />);
  const el = body();
  expect(el.scrollHeight).toBeLessThanOrEqual(el.clientHeight + 1);
  await expect.poll(() => screen.queryByRole('button', { name: /channels$/ })).toBe(null);
});
