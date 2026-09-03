import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { ProgrammeSheet } from '@/features/guide/ProgrammeSheet';
import type { Programme, SearchChannel } from '@/features/guide/api';
import { setAccessToken } from '@/lib/api/client';
import { AuthProvider } from '@/lib/auth/AuthProvider';
import '@/styles/global.css';

/**
 * Layout assertions that jsdom cannot make.
 *
 * Two shipped bugs live here: the Close button was painted over by the hero
 * artwork (and had its clicks taken by it), and it scrolled out of the sheet
 * entirely on a long description. Both passed the jsdom suite, which has no
 * box model and so cannot see either.
 */

const CHANNEL: SearchChannel = {
  id: '11111111-1111-1111-1111-111111111111',
  name: '70s Cinema',
  number: 401,
  logo_url: null,
  group_title: null,
  is_hd: false,
  timezone: 'Europe/London',
  clock_shift_seconds: 0,
};

const PROGRAMME: Programme = {
  id: '22222222-2222-2222-2222-222222222222',
  start: '2026-09-04T20:00:00Z',
  stop: '2026-09-04T22:00:00Z',
  title: 'King Kong',
  sub_title: null,
  // Long enough that the sheet has to scroll.
  description: 'A film about a very large ape and the people who disturb it. '.repeat(60),
  categories: ['Film'],
  episode_num: null,
  year: '1976',
  icon_url: null,
  director: null,
  is_movie: true,
  watched: false,
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

/** A 2x2 PNG, so the hero art has something real to paint. */
const PIXEL =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAF0lEQVR42mP8z8BQz0AEYBxVSF+FABJADveWkH6oAAAAAElFTkSuQmCC';

function renderSheet() {
  vi.stubGlobal(
    'fetch',
    vi.fn((i: RequestInfo | URL) => {
      const path = pathOf(i);
      if (path === '/api/auth/refresh') return Promise.resolve(json({ code: 'x' }, 401));
      if (path.endsWith('/hero')) {
        return Promise.resolve(
          json({
            enriching: false,
            tmdb_connected: true,
            enrichment: {
              tmdb_id: 1,
              title: 'King Kong',
              release_year: '1976',
              overview: null,
              tagline: null,
              rating: null,
              runtime: null,
              director: null,
              genres: [],
              cast: [],
              backdrop_url: PIXEL,
              poster_url: null,
              logo_url: null,
            },
          }),
        );
      }
      return Promise.resolve(json({ code: 'nf' }, 404));
    }),
  );

  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <AuthProvider>
          <ProgrammeSheet channel={CHANNEL} programme={PROGRAMME} onClose={() => undefined} />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function closeButton(): HTMLElement {
  return screen.getByRole('button', { name: 'Close' });
}

/** The element a real click at the button's centre would actually hit. */
function elementAtCentre(el: HTMLElement): Element | null {
  const r = el.getBoundingClientRect();
  return document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
}

beforeEach(() => setAccessToken('t'));
afterEach(() => {
  // This config has no setup file, so RTL's auto-cleanup isn't wired up --
  // without this the previous test's sheet is still mounted and every query
  // finds two of everything.
  cleanup();
  vi.restoreAllMocks();
  setAccessToken(null);
});

test('the Close button is not covered by the hero artwork', async () => {
  renderSheet();
  const button = closeButton();
  // Wait for the backdrop to arrive — before it does there is nothing to be
  // covered by, so asserting too early would pass for the wrong reason.
  await waitFor(() => expect(document.querySelector('[class*="heroArt"]')).toBeTruthy());

  expect(elementAtCentre(button)).toBe(button);
});

test('the Close button stays in view when the description is scrolled', async () => {
  renderSheet();
  const button = closeButton();
  await waitFor(() => expect(document.querySelector('[class*="heroArt"]')).toBeTruthy());

  const body = document.querySelector('[class*="sheetBody"]') as HTMLElement;
  expect(body.scrollHeight).toBeGreaterThan(body.clientHeight); // it really does scroll

  const before = button.getBoundingClientRect().top;
  body.scrollTop = body.scrollHeight;
  await waitFor(() => expect(body.scrollTop).toBeGreaterThan(0));

  expect(button.getBoundingClientRect().top).toBeCloseTo(before, 0);
  expect(elementAtCentre(button)).toBe(button);
});
