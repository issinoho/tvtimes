import { readFileSync } from 'node:fs';

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { SearchPage } from '@/features/search/SearchPage';
import { setAccessToken } from '@/lib/api/client';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <SearchPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  setAccessToken('t');
  document.cookie = 'tvtimes_csrf=x';
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve(json({ results: [] }))),
  );
});

afterEach(() => {
  vi.restoreAllMocks();
  setAccessToken(null);
});

test('seeds the search box from ?q= so another app can hand a title over', async () => {
  renderAt('/search?q=The%20Great%20Escape');
  const box = screen.getByRole('searchbox');
  await waitFor(() => expect(box).toHaveValue('The Great Escape'));
});

test('starts empty with no ?q=', () => {
  renderAt('/search');
  expect(screen.getByRole('searchbox')).toHaveValue('');
});

test('a result row stacks its title and channel instead of running them inline', () => {
  // jsdom does no layout, so this asserts the rule rather than the rendering.
  // Worth having: .name and .meta are spans, and when .main wasn't a column
  // flex container they ran together on one line ("King Kong · 197670s
  // Cinema"), .meta's margin-top was ignored, and .name's ellipsis never
  // applied — so a long title overflowed the row instead of truncating.
  // Vite rewrites import.meta.url to an http URL under test, so this reads
  // from the project root (vitest's cwd) rather than relative to this file.
  const css = readFileSync('src/features/search/search.module.css', 'utf8');
  const main = /\.main\s*\{([^}]*)\}/.exec(css)?.[1] ?? '';
  expect(main).toMatch(/display:\s*flex/);
  expect(main).toMatch(/flex-direction:\s*column/);
});
