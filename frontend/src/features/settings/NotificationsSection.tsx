import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { api, ApiError, unwrap } from '@/lib/api/client';
import type { components } from '@/lib/api/schema';
import styles from '@/features/settings/settings.module.css';

type Target = components['schemas']['NotificationTargetOut'];
type Patch = components['schemas']['NotificationTargetPatch'];

const KEY = ['notification-targets'];

export function NotificationsSection() {
  const qc = useQueryClient();
  const [label, setLabel] = useState('');
  const [url, setUrl] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [tested, setTested] = useState<Record<string, 'ok' | 'fail' | undefined>>({});

  const { data: targets = [] } = useQuery({
    queryKey: KEY,
    queryFn: async () => unwrap(await api.GET('/api/notification-targets')),
  });

  const invalidate = () => void qc.invalidateQueries({ queryKey: KEY });

  const add = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST('/api/notification-targets', {
          body: {
            label: label.trim(),
            url: url.trim(),
            enabled: true,
            send_source_alerts: true,
            send_reminders: true,
          },
        }),
      ),
    onSuccess: () => {
      setLabel('');
      setUrl('');
      setError(null);
      invalidate();
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : 'Could not add that target.'),
  });

  const patch = useMutation({
    mutationFn: async (v: { id: string; body: Patch }) =>
      unwrap(
        await api.PATCH('/api/notification-targets/{target_id}', {
          params: { path: { target_id: v.id } },
          body: v.body,
        }),
      ),
    onSuccess: invalidate,
    onError: (e) => setError(e instanceof ApiError ? e.message : 'Could not save that change.'),
  });

  const remove = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.DELETE('/api/notification-targets/{target_id}', {
          params: { path: { target_id: id } },
        }),
      ),
    onSuccess: invalidate,
    onError: (e) => setError(e instanceof ApiError ? e.message : 'Could not remove that target.'),
  });

  const test = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST('/api/notification-targets/{target_id}/test', {
          params: { path: { target_id: id } },
        }),
      ),
    onSuccess: (_data, id) => flash(id, 'ok'),
    onError: (_err, id) => flash(id, 'fail'),
  });

  function flash(id: string, state: 'ok' | 'fail') {
    setTested((t) => ({ ...t, [id]: state }));
    setTimeout(() => setTested((t) => ({ ...t, [id]: undefined })), 2500);
  }

  const canAdd = label.trim().length > 0 && url.trim().length > 0 && !add.isPending;

  return (
    <section className={styles.section}>
      <h2>
        Push notifications
        {targets.length > 0 ? <span className={styles.badge}>{targets.length}</span> : null}
      </h2>
      <p className={styles.hint}>
        Also deliver source-health alerts and watchlist reminders as push notifications, alongside
        email. Paste an{' '}
        <a
          href="https://github.com/caronc/apprise/wiki#notification-services"
          target="_blank"
          rel="noreferrer noopener"
          className="linkish"
        >
          Apprise URL
        </a>{' '}
        — Gotify, ntfy, Discord, Telegram, Pushover and ~100 others. It usually carries a token, so
        it&rsquo;s stored encrypted and only ever shown back redacted.
      </p>

      {targets.length > 0 ? (
        <ul className={styles.list}>
          {targets.map((t: Target) => (
            <li
              key={t.id}
              className={styles.item}
              style={{
                flexDirection: 'column',
                alignItems: 'stretch',
                gap: '0.55rem',
                opacity: t.enabled ? 1 : 0.55,
              }}
            >
              <div className={styles.ntHead}>
                <span>
                  {t.label}
                  <span className={styles.badge}>{t.service}</span>
                </span>
                <span className={styles.actions} style={{ margin: 0 }}>
                  <button
                    type="button"
                    className={styles.btn}
                    disabled={test.isPending}
                    onClick={() => test.mutate(t.id)}
                  >
                    {tested[t.id] === 'ok' ? 'Sent ✓' : tested[t.id] === 'fail' ? 'Failed' : 'Test'}
                  </button>
                  <button
                    type="button"
                    className={styles.btn}
                    onClick={() => patch.mutate({ id: t.id, body: { enabled: !t.enabled } })}
                  >
                    {t.enabled ? 'Disable' : 'Enable'}
                  </button>
                  <button
                    type="button"
                    className={`${styles.btn} ${styles.danger}`}
                    onClick={() => {
                      if (window.confirm(`Remove “${t.label}”?`)) remove.mutate(t.id);
                    }}
                  >
                    Remove
                  </button>
                </span>
              </div>
              <code className={styles.secret}>{t.redacted_url}</code>
              <div className={styles.ntFlags}>
                <label className={styles.toggle}>
                  <input
                    type="checkbox"
                    checked={t.send_source_alerts}
                    onChange={(e) =>
                      patch.mutate({ id: t.id, body: { send_source_alerts: e.target.checked } })
                    }
                  />
                  Source alerts
                </label>
                <label className={styles.toggle}>
                  <input
                    type="checkbox"
                    checked={t.send_reminders}
                    onChange={(e) =>
                      patch.mutate({ id: t.id, body: { send_reminders: e.target.checked } })
                    }
                  />
                  Reminders
                </label>
              </div>
            </li>
          ))}
        </ul>
      ) : null}

      <div className={styles.ntForm}>
        <input
          className={styles.select}
          placeholder="Label (e.g. Phone via Gotify)"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
        />
        <input
          className={styles.select}
          style={{ flex: '1 1 320px' }}
          placeholder="gotify://gotify.lan/AzB…  ·  ntfy://ntfy.sh/my-topic"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
        />
        <button
          type="button"
          className={`${styles.btn} ${styles.primary}`}
          onClick={() => {
            setError(null);
            add.mutate();
          }}
          disabled={!canAdd}
        >
          {add.isPending ? 'Adding…' : 'Add'}
        </button>
      </div>
      {error ? <p className={styles.error}>{error}</p> : null}
    </section>
  );
}
