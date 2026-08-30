import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { api, ApiError, unwrap } from '@/lib/api/client';
import { registerPasskey } from '@/lib/auth/passkeys';
import {
  browserSupportsPasskeys,
  describePasskeyError,
  passkeysNeedSecureContext,
} from '@/lib/auth/webauthn';
import styles from '@/features/settings/settings.module.css';

const fmtDate = (iso: string) => new Date(iso).toLocaleDateString();

export function PasskeysSection() {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { data: passkeys = [] } = useQuery({
    queryKey: ['passkeys'],
    queryFn: async () => unwrap(await api.GET('/api/account/passkeys')),
  });

  async function add() {
    setBusy(true);
    setError(null);
    const nickname = window.prompt('Name this passkey', 'This device')?.trim();
    if (!nickname) {
      setBusy(false);
      return;
    }
    try {
      await registerPasskey(nickname);
      await qc.invalidateQueries({ queryKey: ['passkeys'] });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : describePasskeyError(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    if (!window.confirm('Remove this passkey? You will no longer be able to sign in with it.'))
      return;
    try {
      unwrap(
        await api.DELETE('/api/account/passkeys/{passkey_id}', {
          params: { path: { passkey_id: id } },
        }),
      );
      await qc.invalidateQueries({ queryKey: ['passkeys'] });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not remove that passkey.');
    }
  }

  return (
    <section className={styles.section}>
      <h2>Passkeys</h2>
      <p className={styles.hint}>
        Phishing-resistant sign-in with your device. Add one per device you use; keep at least two
        so you're never locked out.
      </p>

      {passkeys.length === 0 ? (
        <p className={styles.hint}>No passkeys yet.</p>
      ) : (
        <ul className={styles.list}>
          {passkeys.map((p) => (
            <li key={p.id} className={styles.item}>
              <span>
                {p.nickname}
                {p.backed_up ? <span className={styles.badge}>synced</span> : null}
                <span className={styles.meta}>
                  {' '}
                  · added {fmtDate(p.created_at)}
                  {p.last_used_at ? ` · last used ${fmtDate(p.last_used_at)}` : ''}
                </span>
              </span>
              <button
                type="button"
                className={`${styles.btn} ${styles.danger}`}
                onClick={() => remove(p.id)}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className={styles.actions}>
        <button
          type="button"
          className={`${styles.btn} ${styles.primary}`}
          onClick={add}
          disabled={busy || !browserSupportsPasskeys()}
        >
          {busy ? 'Waiting…' : 'Add a passkey'}
        </button>
      </div>
      {passkeysNeedSecureContext() ? (
        <p className={styles.hint}>
          Passkeys need a secure connection — open tvtimes over HTTPS (or http://localhost) to add
          one.
        </p>
      ) : !browserSupportsPasskeys() ? (
        <p className={styles.hint}>This browser can't create passkeys.</p>
      ) : null}
      {error ? <p className={styles.error}>{error}</p> : null}
    </section>
  );
}
