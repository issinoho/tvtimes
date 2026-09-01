import { useState } from 'react';

import { api, ApiError, unwrap } from '@/lib/api/client';
import { useAuth } from '@/lib/auth/AuthProvider';
import styles from '@/features/settings/settings.module.css';

export function SourceAlertsSection() {
  const { user, refreshMe } = useAuth();
  const enabled = user?.source_alerts_enabled ?? true;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function toggle(next: boolean) {
    setBusy(true);
    setError(null);
    try {
      unwrap(await api.PUT('/api/account/source-alerts', { body: { enabled: next } }));
      await refreshMe();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save that.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={styles.section}>
      <h2>Source alerts</h2>
      <p className={styles.hint}>
        Email everyone on this account when a source breaks, goes stale (stops refreshing) or
        recovers — one message per change. Uses the same mailer as sign-in links.
      </p>
      <label className={styles.toggle}>
        <input
          type="checkbox"
          checked={enabled}
          disabled={busy}
          onChange={(e) => toggle(e.target.checked)}
        />
        Email me about source health changes
      </label>
      {error ? <p className={styles.error}>{error}</p> : null}
    </section>
  );
}
