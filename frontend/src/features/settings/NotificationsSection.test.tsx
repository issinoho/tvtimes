import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { NotificationsSection } from '@/features/settings/NotificationsSection';
import { setAccessToken } from '@/lib/api/client';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

type Target = {
  id: string;
  label: string;
  service: string;
  redacted_url: string;
  enabled: boolean;
  send_source_alerts: boolean;
  send_reminders: boolean;
  created_at: string;
};

function target(over: Partial<Target> = {}): Target {
  return {
    id: 't1',
    label: 'Phone',
    service: 'Gotify',
    redacted_url: 'gotify://gotify.lan/A...n/',
    enabled: true,
    send_source_alerts: true,
    send_reminders: true,
    created_at: '2026-09-01T00:00:00Z',
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

function renderSection() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <NotificationsSection />
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

test('adds a target and shows it in the list', async () => {
  const list: Target[] = [];
  const fetchMock = vi.fn((i: RequestInfo | URL, init?: RequestInit) => {
    const path = pathOf(i);
    const method = methodOf(i, init);
    if (path === '/api/auth/refresh') return Promise.resolve(json({ code: 'x' }, 401));
    if (path === '/api/notification-targets' && method === 'GET')
      return Promise.resolve(json(list));
    if (path === '/api/notification-targets' && method === 'POST') {
      const row = target({ label: 'Desk Gotify' });
      list.push(row);
      return Promise.resolve(json(row, 201));
    }
    return Promise.resolve(json({ code: 'nf' }, 404));
  });
  vi.stubGlobal('fetch', fetchMock);

  renderSection();
  const user = userEvent.setup();
  await user.type(screen.getByPlaceholderText(/Label/), 'Desk Gotify');
  await user.type(screen.getByPlaceholderText(/gotify:\/\//), 'gotify://gotify.lan/AbCdToken');
  await user.click(screen.getByRole('button', { name: 'Add' }));

  await waitFor(() => expect(screen.getByText('Desk Gotify')).toBeInTheDocument());
  expect(screen.getByText('Gotify')).toBeInTheDocument();
  expect(
    fetchMock.mock.calls.some(
      ([i, init]) => pathOf(i) === '/api/notification-targets' && methodOf(i, init) === 'POST',
    ),
  ).toBe(true);
});

test('the Test button pings the test endpoint', async () => {
  const fetchMock = vi.fn((i: RequestInfo | URL, init?: RequestInit) => {
    const path = pathOf(i);
    const method = methodOf(i, init);
    if (path === '/api/auth/refresh') return Promise.resolve(json({ code: 'x' }, 401));
    if (path === '/api/notification-targets' && method === 'GET')
      return Promise.resolve(json([target()]));
    if (path === '/api/notification-targets/t1/test' && method === 'POST')
      return Promise.resolve(json({ message: 'Test notification sent.' }));
    return Promise.resolve(json({ code: 'nf' }, 404));
  });
  vi.stubGlobal('fetch', fetchMock);

  renderSection();
  const user = userEvent.setup();
  await waitFor(() => expect(screen.getByText('Phone')).toBeInTheDocument());
  await user.click(screen.getByRole('button', { name: 'Test' }));

  await waitFor(() => expect(screen.getByRole('button', { name: 'Sent ✓' })).toBeInTheDocument());
});
