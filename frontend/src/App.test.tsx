import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { App } from '@/App';

afterEach(() => {
  vi.restoreAllMocks();
});

test('renders the brand and blurb', () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 500 })));
  render(<App />);
  expect(screen.getByRole('img', { name: 'tvtimes' })).toBeInTheDocument();
  expect(screen.getByText(/multi-tenant TV schedule/i)).toBeInTheDocument();
});

test('shows API version when the health endpoint responds', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: 'ok', version: '9.9.9' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    ),
  );
  render(<App />);
  await waitFor(() => expect(screen.getByText(/API ok · v9\.9\.9/)).toBeInTheDocument());
});
