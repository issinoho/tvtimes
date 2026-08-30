import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { AuthShell, Button, Callout, Field, FootNote, Heading } from '@/components/ui';
import { api, ApiError, unwrap } from '@/lib/api/client';

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const token = params.get('token');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!token) {
      setError('This reset link is missing its token.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      unwrap(await api.POST('/api/auth/password/reset', { body: { token, password } }));
      setDone(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not reset your password.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell>
      <Heading title="Choose a new password" />
      {error ? <Callout kind="error">{error}</Callout> : null}
      {done ? (
        <>
          <Callout kind="success">Password updated. All other sessions were signed out.</Callout>
          <Link to="/login">
            <Button>Sign in</Button>
          </Link>
        </>
      ) : (
        <form onSubmit={onSubmit}>
          <Field
            label="New password"
            type="password"
            autoComplete="new-password"
            required
            minLength={10}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <Button type="submit" busy={busy}>
            Update password
          </Button>
        </form>
      )}
      <FootNote>
        <Link to="/login">Back to sign in</Link>
      </FootNote>
    </AuthShell>
  );
}
