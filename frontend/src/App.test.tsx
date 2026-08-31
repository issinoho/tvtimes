import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { AuthProvider } from '@/lib/auth/AuthProvider';
import { AppRoutes } from '@/routes/AppRoutes';

type Handler = () => Response;

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

function mockApi(routes: Record<string, Handler>) {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      const path = new URL(url, 'http://localhost').pathname;
      const handler = routes[path];
      return Promise.resolve(handler ? handler() : json({ code: 'not_found', message: path }, 404));
    }),
  );
}

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter
        initialEntries={[path]}
        future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
      >
        <AuthProvider>
          <AppRoutes />
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const ME = {
  id: '00000000-0000-0000-0000-000000000001',
  email: 'sam@example.com',
  display_name: 'Sam',
  email_verified: true,
  tenant_id: '00000000-0000-0000-0000-000000000002',
  default_timezone: 'UTC',
  totp_enabled: false,
  passkey_count: 1,
  tmdb_connected: false,
};

beforeEach(() => {
  document.cookie = 'tvtimes_csrf=csrf-token';
  sessionStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

test('an unauthenticated visitor lands on the sign-in screen', async () => {
  mockApi({ '/api/auth/refresh': () => json({ code: 'token_invalid' }, 401) });
  renderAt('/');
  await waitFor(() => expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument());
});

test('a refreshable session with a passkey lands in the app', async () => {
  mockApi({
    '/api/auth/refresh': () =>
      json({ access_token: 'a.b.c', token_type: 'bearer', expires_at: '' }),
    '/api/account/me': () => json(ME),
    '/api/sources': () => json([]),
    '/api/guide': () => json({ from: '', to: '', channels: [] }),
  });
  renderAt('/guide');
  await waitFor(() => expect(screen.getByText(/Connect a source/i)).toBeInTheDocument());
  expect(screen.getByRole('button', { name: 'Now' })).toBeInTheDocument();
});

test('a session with no passkey is pushed into onboarding', async () => {
  mockApi({
    '/api/auth/refresh': () =>
      json({ access_token: 'a.b.c', token_type: 'bearer', expires_at: '' }),
    '/api/account/me': () => json({ ...ME, passkey_count: 0 }),
  });
  renderAt('/');
  await waitFor(() =>
    expect(screen.getByRole('heading', { name: /add a passkey/i })).toBeInTheDocument(),
  );
});

test('the sign-up form confirms an email was sent', async () => {
  const { default: userEvent } = await import('@testing-library/user-event');
  mockApi({
    '/api/auth/refresh': () => json({ code: 'token_invalid' }, 401),
    '/api/auth/register': () => json({ message: 'ok' }, 202),
  });
  renderAt('/signup');
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('Your name'), 'Sam');
  await user.type(screen.getByLabelText('Email'), 'sam@example.com');
  await user.type(screen.getByLabelText('Password'), 'correct horse battery');
  await user.click(screen.getByRole('button', { name: /create account/i }));
  await waitFor(() => expect(screen.getByText(/check your email/i)).toBeInTheDocument());
});
