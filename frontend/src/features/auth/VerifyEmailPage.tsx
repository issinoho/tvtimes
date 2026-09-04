import { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';

import { AuthShell, Button, Callout, Heading } from '@/components/ui';
import { api, unwrap } from '@/lib/api/client';

type State = 'working' | 'ok' | 'bad';

export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get('token');
  // A missing token is knowable at render, so it's the initial state rather
  // than something an effect sets on the way in -- that was a wasted render
  // and a cascading-update warning for a value nothing had to wait for.
  const [state, setState] = useState<State>(token ? 'working' : 'bad');
  const ran = useRef(false);

  useEffect(() => {
    if (!token || ran.current) return;
    ran.current = true;
    void (async () => {
      try {
        unwrap(await api.POST('/api/auth/verify', { body: { token } }));
        setState('ok');
      } catch {
        // Every failure reads the same to the visitor: the link didn't work.
        setState('bad');
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
