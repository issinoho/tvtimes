import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { AuthShell, Button, Callout, Heading } from '@/components/ui';
import { api, ApiError, unwrap } from '@/lib/api/client';

type State = 'working' | 'ok' | 'bad';

export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get('token');
  const [state, setState] = useState<State>('working');
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    if (!token) {
      setState('bad');
      return;
    }
    void (async () => {
      try {
        unwrap(await api.POST('/api/auth/verify', { body: { token } }));
        setState('ok');
      } catch (err) {
        setState(err instanceof ApiError ? 'bad' : 'bad');
      }
    })();
  }, [token]);

  return (
    <AuthShell>
      {state === 'working' && <Heading title="Confirming your email…" />}
      {state === 'ok' && (
        <>
          <Heading title="Email confirmed" sub="Your account is ready." />
          <Callout kind="success">You can sign in now.</Callout>
          <Link to="/login">
            <Button>Continue to sign in</Button>
          </Link>
        </>
      )}
      {state === 'bad' && (
        <>
          <Heading
            title="That link didn't work"
            sub="It may have expired or already been used. Sign in and we'll send a fresh one if needed."
          />
          <Link to="/login">
            <Button variant="secondary">Back to sign in</Button>
          </Link>
        </>
      )}
    </AuthShell>
  );
}
