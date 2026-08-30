import { useState } from 'react';
import { Link } from 'react-router-dom';

import { AuthShell, Button, Callout, Field, FootNote, Heading } from '@/components/ui';
import { api, ApiError, unwrap } from '@/lib/api/client';

export function SignUpPage() {
  const [email, setEmail] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      unwrap(
        await api.POST('/api/auth/register', {
          body: { email, display_name: displayName, password },
        }),
      );
      setSent(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create your account.');
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <AuthShell>
        <Heading
          title="Check your email"
          sub={`If ${email} can be used, a confirmation link is on its way. Open it to finish setting up your account.`}
        />
        <Callout kind="success">You can close this tab — the link opens tvtimes for you.</Callout>
        <FootNote>
          <Link to="/login">Back to sign in</Link>
        </FootNote>
      </AuthShell>
    );
  }

  return (
    <AuthShell>
      <Heading
        title="Create your account"
        sub="Free, and yours. You'll add a passkey right after."
      />
      {error ? <Callout kind="error">{error}</Callout> : null}
      <form onSubmit={onSubmit}>
        <Field
          label="Your name"
          autoComplete="name"
          required
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
        />
        <Field
          label="Email"
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <Field
          label="Password"
          type="password"
          autoComplete="new-password"
          required
          minLength={10}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <Button type="submit" busy={busy}>
          Create account
        </Button>
      </form>
      <FootNote>
        Already have an account? <Link to="/login">Sign in</Link>
      </FootNote>
    </AuthShell>
  );
}
