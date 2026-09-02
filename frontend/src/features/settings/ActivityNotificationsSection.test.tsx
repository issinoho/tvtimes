import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { ActivityNotificationsSection } from '@/features/settings/ActivityNotificationsSection';
import { setAccessToken } from '@/lib/api/client';
import { AuthProvider } from '@/lib/auth/AuthProvider';

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function me(over: Record<string, unknown> = {}) {
  return {
    id: 'u',
    email: 'a@b.c',
    display_name: 'A',
    email_verified: true,
    tenant_id: 't',
    default_timezone: 'UTC',
    totp_enabled: false,
    passkey_count: 1,
    tmdb_connected: false,
    source_alerts_enabled: true,
    notify_on_reminder_set: false,
    notify_on_title_watch_set: false,
    notify_on_play: false,
    notify_on_watchlist_remove: false,
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
        <AuthProvider>
          <ActivityNotificationsSection />
        </AuthProvider>
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

async function bodyOf(i: RequestInfo | URL, init?: RequestInit): Promise<unknown> {
  const raw = init?.body ?? (i instanceof Request ? await i.clone().text() : undefined);
  return typeof raw === 'string' && raw ? JSON.parse(raw) : {};
}

test('toggling a category PUTs that field and re-reads /me', async () => {
  let play = false;
  const bodies: unknown[] = [];
  const fetchMock = vi.fn(async (i: RequestInfo | URL, init?: RequestInit) => {
    const path = pathOf(i);
    const method = methodOf(i, init);
    if (path === '/api/auth/refresh') return json({ code: 'x' }, 401);
    if (path === '/api/account/me') return json(me({ notify_on_play: play }));
    if (path === '/api/account/activity-notifications' && method === 'PUT') {
      bodies.push(await bodyOf(i, init));
      play = true;
      return json({ message: 'ok' });
    }
    return json({ code: 'nf' }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);

  renderSection();
  const user = userEvent.setup();

  const playToggle = await screen.findByRole('checkbox', { name: /channel is played/i });
  expect(playToggle).not.toBeChecked();
  // the other three start unchecked and independent
  expect(screen.getByRole('checkbox', { name: /reminder is set/i })).not.toBeChecked();
  await user.click(playToggle);

  await waitFor(() => expect(playToggle).toBeChecked());
  expect(bodies).toEqual([{ play: true }]);
});
