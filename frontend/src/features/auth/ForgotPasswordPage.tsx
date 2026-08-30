import { useState } from 'react';
import { Link } from 'react-router-dom';

import { AuthShell, Button, Callout, Field, FootNote, Heading } from '@/components/ui';
import { api } from '@/lib/api/client';

export function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    // The endpoint is deliberately generic; ignore the outcome.
    await api.POST('/api/auth/password/forgot', { body: { email } });
    setBusy(false);
    setSent(true);
  }

  return (
    <AuthShell>
      <Heading
        title="Reset your password"
        sub="We'll email you a link if there's an account for this address."
      />
      {sent ? (
        <Callout kind="success">If that account exists, a reset link is on its way.</Callout>
      ) : (
        <form onSubmit={onSubmit}>
          <Field
            label="Email"
            type="email"
            autoComplete="username"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <Button type="submit" busy={busy}>
            Send reset link
          </Button>
        </form>
      )}
      <FootNote>
        <Link to="/login">Back to sign in</Link>
      </FootNote>
    </AuthShell>
  );
}
