import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { api, ApiError, unwrap } from '@/lib/api/client';
import styles from '@/features/settings/settings.module.css';

const fmtDate = (iso: string) => new Date(iso).toLocaleString();

function describeUA(ua: string | null | undefined): string {
  if (!ua) return 'Unknown device';
  if (/mobile/i.test(ua)) return 'Mobile browser';
  if (/edg/i.test(ua)) return 'Edge';
  if (/chrome/i.test(ua)) return 'Chrome';
  if (/firefox/i.test(ua)) return 'Firefox';
  if (/safari/i.test(ua)) return 'Safari';
  return ua.slice(0, 40);
}

export function SessionsSection() {
  const qc = useQueryClient();
  const [error, setError] = useState<string | null>(null);

  const { data: sessions = [] } = useQuery({
    queryKey: ['sessions'],
    queryFn: async () => unwrap(await api.GET('/api/account/sessions')),
  });

  async function revoke(id: string) {
    try {
      unwrap(
        await api.DELETE('/api/account/sessions/{session_id}', {
          params: { path: { session_id: id } },
        }),
      );
      await qc.invalidateQueries({ queryKey: ['sessions'] });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not revoke that session.');
    }
  }

  async function revokeOthers() {
    if (!window.confirm('Sign out every other device?')) return;
    try {
      unwrap(await api.DELETE('/api/account/sessions'));
      await qc.invalidateQueries({ queryKey: ['sessions'] });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not sign out other sessions.');
    }
  }

  const others = sessions.filter((s) => !s.current).length;

  return (
    <section className={styles.section}>
      <h2>Active sessions</h2>
      <p className={styles.hint}>Where you're signed in. Revoke anything you don't recognise.</p>

      <ul className={styles.list}>
        {sessions.map((s) => (
          <li key={s.id} className={styles.item}>
            <span>
              {describeUA(s.user_agent)}
              {s.current ? <span className={styles.badge}>this device</span> : null}
              <span className={styles.meta}>
                {' '}
                · {s.ip ?? 'unknown IP'} · since {fmtDate(s.created_at)}
              </span>
            </span>
            {!s.current ? (
              <button
                type="button"
                className={`${styles.btn} ${styles.danger}`}
                onClick={() => revoke(s.id)}
              >
                Revoke
              </button>
            ) : null}
          </li>
        ))}
      </ul>

      {others > 0 ? (
        <div className={styles.actions}>
          <button type="button" className={`${styles.btn} ${styles.danger}`} onClick={revokeOthers}>
            Sign out other devices ({others})
          </button>
        </div>
      ) : null}
      {error ? <p className={styles.error}>{error}</p> : null}
    </section>
  );
}
