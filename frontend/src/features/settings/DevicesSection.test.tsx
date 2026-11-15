import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { DevicesSection } from '@/features/settings/DevicesSection';
import { setAccessToken } from '@/lib/api/client';

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

async function bodyOf(i: RequestInfo | URL, init?: RequestInit): Promise<unknown> {
  const raw = init?.body ?? (i instanceof Request ? await i.clone().text() : undefined);
  return typeof raw === 'string' && raw ? JSON.parse(raw) : {};
}

const DEVICE = {
  id: 'd1',
  name: 'Living room Fire TV',
  approved_at: '2026-11-15T22:00:00Z',
  last_used_at: null,
  paired: true,
};

function renderSection() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <DevicesSection />
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

test('approving the code from the TV posts it and lists the device', async () => {
  const devices: (typeof DEVICE)[] = [];
  const posted: unknown[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (i: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(i);
      if (path === '/api/devices' && methodOf(i, init) === 'POST') {
        posted.push(await bodyOf(i, init));
        devices.push(DEVICE);
        return json({ ...DEVICE, paired: false });
      }
      if (path === '/api/devices') return json(devices);
      return json({ code: 'nf' }, 404);
    }),
  );

  renderSection();
  const user = userEvent.setup();
  const approve = screen.getByRole('button', { name: 'Approve' });
  expect(approve).toBeDisabled();
  await user.type(screen.getByLabelText('Code shown on the TV'), 'k7qm 4xr2');
  await user.click(approve);

  await waitFor(() =>
    expect(screen.getByText(/Approved “Living room Fire TV”/)).toBeInTheDocument(),
  );
  expect(posted).toEqual([{ code: 'k7qm 4xr2' }]);
  await waitFor(() => expect(screen.getByText('Living room Fire TV')).toBeInTheDocument());
});

test('a wrong code shows the server message', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn((i: RequestInfo | URL, init?: RequestInit) => {
      const path = pathOf(i);
      if (path === '/api/devices' && methodOf(i, init) === 'POST')
        return Promise.resolve(json({ detail: 'That code is invalid or has expired.' }, 400));
      if (path === '/api/devices') return Promise.resolve(json([]));
      return Promise.resolve(json({ code: 'nf' }, 404));
    }),
  );

  renderSection();
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('Code shown on the TV'), 'AAAABBBB');
  await user.click(screen.getByRole('button', { name: 'Approve' }));
  await waitFor(() => expect(screen.getByText(/invalid or has expired/)).toBeInTheDocument());
});
