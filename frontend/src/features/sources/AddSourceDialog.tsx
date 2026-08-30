import { useEffect, useState } from 'react';

import { ApiError } from '@/lib/api/client';
import { useDialogFocus } from '@/lib/useDialogFocus';
import { useCreateSource, type SourceCreate, type SourceKind } from '@/features/sources/api';
import styles from '@/features/sources/sources.module.css';

const KIND_LABEL: Record<SourceKind, string> = {
  m3u: 'M3U playlist',
  xtream: 'Xtream Codes',
  stalker: 'Stalker portal',
};

function Field({
  label,
  value,
  onChange,
  type = 'text',
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  placeholder?: string;
}) {
  return (
    <label className={styles.field}>
      <span>{label}</span>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

export function AddSourceDialog({ onClose }: { onClose: () => void }) {
  const create = useCreateSource();
  const dialogRef = useDialogFocus<HTMLDivElement>();
  const [kind, setKind] = useState<SourceKind>('m3u');
  const [displayName, setDisplayName] = useState('');
  const [f, setF] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const set = (k: string) => (v: string) => setF((prev) => ({ ...prev, [k]: v }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const common = {
      display_name: displayName,
      clock_shift_seconds: 0,
      refresh_interval_minutes: 360,
    };
    let body: SourceCreate;
    if (kind === 'm3u') {
      body = { ...common, kind: 'm3u', url: f.url ?? '' };
    } else if (kind === 'xtream') {
      body = {
        ...common,
        kind: 'xtream',
        server_url: f.server_url ?? '',
        username: f.username ?? '',
        password: f.password ?? '',
        output: 'ts',
      };
    } else {
      body = {
        ...common,
        kind: 'stalker',
        portal_url: f.portal_url ?? '',
        mac: f.mac ?? '',
        serial: null,
        device_id: null,
        stb_type: 'MAG250',
      };
    }
    try {
      await create.mutateAsync(body);
      onClose();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not add that source.');
    }
  }

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div
        ref={dialogRef}
        className={styles.dialog}
        role="dialog"
        aria-modal="true"
        aria-label="Add a source"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <h2>Add a source</h2>
        <div className={styles.kinds}>
          {(Object.keys(KIND_LABEL) as SourceKind[]).map((k) => (
            <button key={k} type="button" data-active={k === kind} onClick={() => setKind(k)}>
              {KIND_LABEL[k]}
            </button>
          ))}
        </div>

        <form onSubmit={submit}>
          {error ? <p className={styles.err}>{error}</p> : null}
          <Field
            label="Name"
            value={displayName}
            onChange={setDisplayName}
            placeholder="Living room TV"
          />

          {kind === 'm3u' && (
            <Field
              label="Playlist URL"
              value={f.url ?? ''}
              onChange={set('url')}
              placeholder="https://example.com/playlist.m3u"
            />
          )}
          {kind === 'xtream' && (
            <>
              <Field
                label="Server URL"
                value={f.server_url ?? ''}
                onChange={set('server_url')}
                placeholder="http://panel.example.com:8080"
              />
              <Field label="Username" value={f.username ?? ''} onChange={set('username')} />
              <Field
                label="Password"
                type="password"
                value={f.password ?? ''}
                onChange={set('password')}
              />
            </>
          )}
          {kind === 'stalker' && (
            <>
              <Field
                label="Portal URL"
                value={f.portal_url ?? ''}
                onChange={set('portal_url')}
                placeholder="http://portal.example.com/c/"
              />
              <Field
                label="MAC address"
                value={f.mac ?? ''}
                onChange={set('mac')}
                placeholder="00:1A:79:xx:xx:xx"
              />
            </>
          )}

          <div className={styles.actions}>
            <button type="button" className={styles.btn} onClick={onClose}>
              Cancel
            </button>
            <button
              type="submit"
              className={`${styles.btn} ${styles.primary}`}
              disabled={create.isPending || !displayName.trim()}
            >
              {create.isPending ? 'Adding…' : 'Add source'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
