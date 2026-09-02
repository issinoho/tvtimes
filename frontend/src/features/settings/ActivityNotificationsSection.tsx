import { useState } from 'react';

import { api, ApiError, unwrap } from '@/lib/api/client';
import { useAuth } from '@/lib/auth/AuthProvider';
import type { Me } from '@/lib/auth/types';
import styles from '@/features/settings/settings.module.css';

type Field = 'reminder_set' | 'title_watch_set' | 'play' | 'watchlist_remove';

const ROWS: { field: Field; meKey: keyof Me; label: string }[] = [
  {
    field: 'reminder_set',
    meKey: 'notify_on_reminder_set',
    label: 'A reminder is set on a programme',
  },
  {
    field: 'title_watch_set',
    meKey: 'notify_on_title_watch_set',
    label: 'A title is added to the watchlist',
  },
  { field: 'play', meKey: 'notify_on_play', label: 'A channel is played' },
  {
    field: 'watchlist_remove',
    meKey: 'notify_on_watchlist_remove',
    label: 'A watchlist entry is removed',
  },
];

export function ActivityNotificationsSection() {
  const { user, refreshMe } = useAuth();
  const [busy, setBusy] = useState<Field | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function toggle(field: Field, next: boolean) {
    setBusy(field);
    setError(null);
    try {
      unwrap(await api.PUT('/api/account/activity-notifications', { body: { [field]: next } }));
      await refreshMe();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save that.');
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className={styles.section}>
      <h2>Activity notifications</h2>
      <p className={styles.hint}>
        Push a notification to every enabled target above when someone on this account takes one of
        these actions. Each is a separate opt-in and applies to the whole account. Push only — these
        never send email.
      </p>
      <div className={styles.toggleList}>
        {ROWS.map(({ field, meKey, label }) => (
          <label key={field} className={styles.toggle}>
            <input
              type="checkbox"
              checked={Boolean(user?.[meKey])}
              disabled={busy !== null}
              onChange={(e) => toggle(field, e.target.checked)}
            />
            {label}
          </label>
        ))}
      </div>
      {error ? <p className={styles.error}>{error}</p> : null}
    </section>
  );
}
