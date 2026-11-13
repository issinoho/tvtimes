import { useEffect, useState } from 'react';

import { ApiError } from '@/lib/api/client';
import { useDialogFocus } from '@/lib/useDialogFocus';
import { Field } from '@/features/sources/AddSourceDialog';
import { usePatchSource, type SourceOut } from '@/features/sources/api';
import styles from '@/features/sources/sources.module.css';
import type { components } from '@/lib/api/schema';

type Patch = components['schemas']['SourcePatchIn'];

function readZones(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (k: string) => string[] };
  if (typeof intl.supportedValuesOf === 'function') return intl.supportedValuesOf('timeZone');
  return ['UTC', 'Europe/London', 'America/New_York', 'America/Los_Angeles', 'Australia/Sydney'];
}

const ZONES = readZones();

const INTERVALS: [number, string][] = [
  [60, 'Every hour'],
  [180, 'Every 3 hours'],
  [360, 'Every 6 hours'],
  [720, 'Every 12 hours'],
  [1440, 'Once a day'],
  [10080, 'Once a week'],
];

const KEEP = 'Leave blank to keep the current one';

/**
 * Edit a source in place: its name, how often it refreshes, its timezone and
 * where it connects. The saved credentials never come back from the API, so
 * connection fields start empty and a blank one keeps what is stored. A new
 * connection re-fetches the channel list; channels that are still there keep
 * their guide data, overrides and watchlist entries.
 */
export function EditSourceDialog({ source, onClose }: { source: SourceOut; onClose: () => void }) {
  const patch = usePatchSource(source.id);
  const dialogRef = useDialogFocus<HTMLDivElement>();
  const [name, setName] = useState(source.display_name);
  const [interval, setRefreshEvery] = useState(source.refresh_interval_minutes);
  const [zone, setZone] = useState(source.timezone_override ?? '');
  // An HDHomeRun address isn't a secret (the summary already shows it), so it
  // starts filled in; blank there means auto-discover, not "keep".
  const [deviceUrl, setDeviceUrl] = useState(
    source.kind === 'hdhomerun' && source.config_summary.startsWith('http')
      ? source.config_summary
      : '',
  );
  const [f, setF] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const set = (k: string) => (v: string) => setF((prev) => ({ ...prev, [k]: v }));
  const typed = (k: string) => (f[k] ?? '').trim() || undefined;

  function connection(): Patch['config'] {
    switch (source.kind) {
      case 'm3u':
        return typed('url') ? { kind: 'm3u', url: typed('url') } : undefined;
      case 'xtream': {
        const c = {
          server_url: typed('server_url'),
          username: typed('username'),
          password: f.password || undefined,
        };
        return Object.values(c).some(Boolean) ? { kind: 'xtream', ...c } : undefined;
      }
      case 'stalker': {
        const c = { portal_url: typed('portal_url'), mac: typed('mac') };
        return Object.values(c).some(Boolean) ? { kind: 'stalker', ...c } : undefined;
      }
      case 'hdhomerun':
        return { kind: 'hdhomerun', device_url: deviceUrl.trim() };
      default:
        return undefined;
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const body: Patch = {};
    if (name.trim() !== source.display_name) body.display_name = name.trim();
    if (interval !== source.refresh_interval_minutes) body.refresh_interval_minutes = interval;
    if ((zone || null) !== source.timezone_override) body.timezone_override = zone || null;
    const config = connection();
    if (config) body.config = config;
    try {
      if (Object.keys(body).length) await patch.mutateAsync(body);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not save those changes.');
    }
  }

  const intervals = INTERVALS.some(([m]) => m === source.refresh_interval_minutes)
    ? INTERVALS
    : [
        ...INTERVALS,
        [source.refresh_interval_minutes, `Every ${source.refresh_interval_minutes} minutes`] as [
          number,
          string,
        ],
      ].sort((a, b) => a[0] - b[0]);

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div
        ref={dialogRef}
        className={`${styles.dialog} ${styles.dialogTall}`}
        role="dialog"
        aria-modal="true"
        aria-label="Edit source"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <h2>Edit source</h2>
        <form onSubmit={submit}>
          {error ? <p className={styles.err}>{error}</p> : null}
          <Field label="Name" value={name} onChange={setName} />

          <label className={styles.field}>
            <span>Refresh channels</span>
            <select value={interval} onChange={(e) => setRefreshEvery(Number(e.target.value))}>
              {intervals.map(([m, label]) => (
                <option key={m} value={m}>
                  {label}
                </option>
              ))}
            </select>
          </label>

          <label className={styles.field}>
            <span>Timezone</span>
            <select value={zone} onChange={(e) => setZone(e.target.value)}>
              <option value="">Account default</option>
              {ZONES.map((z) => (
                <option key={z} value={z}>
                  {z}
                </option>
              ))}
            </select>
          </label>

          {source.kind === 'connector' ? (
            <p className={styles.hint}>
              This source is fed by a connector agent — change its tuner there.
            </p>
          ) : (
            <>
              <p className={styles.legend}>Connection</p>
              <p className={styles.hint}>
                Currently {source.config_summary}. Saving a new connection re-fetches the channel
                list; channels that are still there keep their guide and settings.
              </p>
            </>
          )}

          {source.kind === 'm3u' && (
            <Field
              label="Playlist URL"
              value={f.url ?? ''}
              onChange={set('url')}
              placeholder={KEEP}
            />
          )}
          {source.kind === 'xtream' && (
            <>
              <Field
                label="Server URL"
                value={f.server_url ?? ''}
                onChange={set('server_url')}
                placeholder={KEEP}
              />
              <Field
                label="Username"
                value={f.username ?? ''}
                onChange={set('username')}
                placeholder={KEEP}
              />
              <Field
                label="Password"
                type="password"
                value={f.password ?? ''}
                onChange={set('password')}
                placeholder={KEEP}
              />
            </>
          )}
          {source.kind === 'stalker' && (
            <>
              <Field
                label="Portal URL"
                value={f.portal_url ?? ''}
                onChange={set('portal_url')}
                placeholder={KEEP}
              />
              <Field
                label="MAC address"
                value={f.mac ?? ''}
                onChange={set('mac')}
                placeholder={KEEP}
              />
            </>
          )}
          {source.kind === 'hdhomerun' && (
            <>
              <Field
                label="Device address (optional)"
                value={deviceUrl}
                onChange={setDeviceUrl}
                placeholder="http://192.168.1.50"
              />
              <p className={styles.hint}>Leave blank to auto-discover on your network.</p>
            </>
          )}

          <div className={styles.actions}>
            <button type="button" className={styles.btn} onClick={onClose}>
              Cancel
            </button>
            <button
              type="submit"
              className={`${styles.btn} ${styles.primary}`}
              disabled={patch.isPending || !name.trim()}
            >
              {patch.isPending ? 'Saving…' : 'Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
