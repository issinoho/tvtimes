import { useState } from 'react';

import { api, ApiError, unwrap } from '@/lib/api/client';
import { useAuth } from '@/lib/auth/AuthProvider';
import styles from '@/features/settings/settings.module.css';

function readZones(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (k: string) => string[] };
  if (typeof intl.supportedValuesOf === 'function') return intl.supportedValuesOf('timeZone');
  return ['UTC', 'Europe/London', 'America/New_York', 'America/Los_Angeles', 'Australia/Sydney'];
}

const ZONES = readZones();

export function TimezoneSection() {
  const { user, refreshMe } = useAuth();
  const [value, setValue] = useState(user?.default_timezone ?? 'UTC');
  const [state, setState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);

  async function save() {
    setState('saving');
    setError(null);
    try {
      unwrap(await api.PUT('/api/account/timezone', { body: { timezone: value } }));
      await refreshMe();
      setState('saved');
    } catch (err) {
      setState('error');
      setError(err instanceof ApiError ? err.message : 'Could not save.');
    }
  }

  return (
    <section className={styles.section}>
      <h2>Timezone</h2>
      <p className={styles.hint}>
        The default clock for your guide. Each source can override this later for feeds in another
        region.
      </p>
      <select
        className={styles.select}
        value={value}
        onChange={(e) => {
          setValue(e.target.value);
          setState('idle');
        }}
        aria-label="Default timezone"
      >
        {ZONES.map((z) => (
          <option key={z} value={z}>
            {z}
          </option>
        ))}
      </select>
      <div className={styles.actions}>
        <button
          type="button"
          className={`${styles.btn} ${styles.primary}`}
          onClick={save}
          disabled={state === 'saving' || value === user?.default_timezone}
        >
          {state === 'saving' ? 'Saving…' : 'Save'}
        </button>
      </div>
      {state === 'saved' ? <p className={styles.ok}>Saved.</p> : null}
      {error ? <p className={styles.error}>{error}</p> : null}
    </section>
  );
}
