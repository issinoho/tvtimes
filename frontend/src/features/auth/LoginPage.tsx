import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { AuthShell, Button, Callout, Field, FootNote, Heading, OrDivider } from '@/components/ui';
import { ApiError } from '@/lib/api/client';
import { useAuth } from '@/lib/auth/AuthProvider';
import { browserSupportsPasskeys } from '@/lib/auth/webauthn';

export function LoginPage() {
  const { loginWithPassword, completeMfa, loginWithPasskey } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [mfaToken, setMfaToken] = useState<string | null>(null);
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const triedAutofill = useRef(false);

  const done = () => navigate('/', { replace: true });

  // Conditional-UI passkey autofill: offered silently, never blocks the form.
  useEffect(() => {
    if (triedAutofill.current || !browserSupportsPasskeys()) return;
    triedAutofill.current = true;
    void loginWithPasskey()
      .then(done)
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function onPasswordSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const challenge = await loginWithPassword(email, password);
      if (challenge) setMfaToken(challenge.mfaToken);
      else await done();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not sign in.');
    } finally {
      setBusy(false);
    }
  }

  async function onMfaSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!mfaToken) return;
    setBusy(true);
    setError(null);
    try {
      await completeMfa(mfaToken, code.trim());
      await done();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'That code was not accepted.');
    } finally {
      setBusy(false);
    }
  }

  async function onPasskeyClick() {
    setBusy(true);
    setError(null);
    try {
      await loginWithPasskey(email || undefined);
      await done();
    } catch {
      setError('Passkey sign-in was cancelled or failed.');
    } finally {
      setBusy(false);
    }
  }

  if (mfaToken) {
    return (
      <AuthShell>
        <Heading
          title="One more step"
          sub="Enter the 6-digit code from your authenticator app, or a recovery code."
        />
        {error ? <Callout kind="error">{error}</Callout> : null}
        <form onSubmit={onMfaSubmit}>
          <Field
            label="Authentication code"
            inputMode="text"
            autoComplete="one-time-code"
            autoFocus
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
          <Button type="submit" busy={busy}>
            Verify
          </Button>
        </form>
      </AuthShell>
    );
  }

  return (
    <AuthShell>
      <Heading title="Sign in" sub="Use a passkey, or your email and password." />
      {error ? <Callout kind="error">{error}</Callout> : null}

      {browserSupportsPasskeys() ? (
        <>
          <Button variant="secondary" onClick={onPasskeyClick} busy={busy}>
            Sign in with a passkey
          </Button>
          <OrDivider />
        </>
      ) : null}

      <form onSubmit={onPasswordSubmit}>
        <Field
          label="Email"
          type="email"
          autoComplete="username webauthn"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <Field
          label="Password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <Button type="submit" busy={busy}>
          Sign in
        </Button>
      </form>

      <FootNote>
        <Link to="/forgot">Forgot your password?</Link>
      </FootNote>
      <FootNote>
        New here? <Link to="/signup">Create an account</Link>
      </FootNote>
    </AuthShell>
  );
}
