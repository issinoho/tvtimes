import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { AuthShell, Button, Callout, FootNote, Heading } from '@/components/ui';
import { useAuth } from '@/lib/auth/AuthProvider';
import { SKIP_PASSKEY_KEY } from '@/lib/auth/constants';
import { registerPasskey } from '@/lib/auth/passkeys';
import { browserSupportsPasskeys } from '@/lib/auth/webauthn';

export function OnboardingPasskeyPage() {
  const { refreshMe } = useAuth();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function add() {
    setBusy(true);
    setError(null);
    try {
      await registerPasskey('This device');
      await refreshMe();
      navigate('/', { replace: true });
    } catch {
      setError(
        'Passkey setup was cancelled or not supported here. You can add one later in Settings.',
      );
    } finally {
      setBusy(false);
    }
  }

  function skip() {
    sessionStorage.setItem(SKIP_PASSKEY_KEY, '1');
    navigate('/', { replace: true });
  }

  return (
    <AuthShell>
      <Heading
        title="Add a passkey"
        sub="Passkeys sign you in with your fingerprint, face, or device PIN — nothing to remember, nothing to phish."
      />
      {error ? <Callout kind="error">{error}</Callout> : null}
      {browserSupportsPasskeys() ? (
        <Button onClick={add} busy={busy}>
          Create a passkey
        </Button>
      ) : (
        <Callout kind="info">
          This browser can't create passkeys. You can add one later from another device.
        </Callout>
      )}
      <FootNote>
        <button type="button" className="linkish" onClick={skip}>
          Skip for now
        </button>
      </FootNote>
    </AuthShell>
  );
}
