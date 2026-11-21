import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import type { SourceOut } from '@/features/sources/api';
import { curlExample, hookUrl } from '@/features/sources/urlUpdates';
import { api, ApiError, unwrap } from '@/lib/api/client';
import styles from '@/features/sources/sources.module.css';

const fmt = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleString() : 'never');

/** The URL field a push replaces, in this source kind's own words. */
const FIELD: Record<string, string> = {
  m3u: 'playlist URL',
  xtream: 'server URL',
  stalker: 'portal URL',
};

/**
 * Remote URL updates: a token, scoped to this one source, that lets another
 * system push a new address for a feed whose URL keeps changing. Shown once.
 * A push replaces only the URL — credentials are kept — and refreshes the
 * source in place, so channels keep their guide data.
 */
export function UrlUpdatesPanel({ source }: { source: SourceOut }) {
  const qc = useQueryClient();
  const [token, setToken] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!source.url_updates_supported) return null;
  const enabled = Boolean(source.update_token_set_at);
  const params = { params: { path: { source_id: source.id } } };
  const example = curlExample(window.location.origin, token ?? '<token>');

  const invalidate = () => qc.invalidateQueries({ queryKey: ['sources'] });

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      const res = unwrap(await api.POST('/api/sources/{source_id}/update-token', params));
      setToken(res.token);
      await invalidate();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create an update token.');
    } finally {
      setBusy(false);
    }
  }

  async function disable() {
    setBusy(true);
    setError(null);
    try {
      unwrap(await api.DELETE('/api/sources/{source_id}/update-token', params));
      setToken(null);
      await invalidate();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not turn off remote updates.');
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(example);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }

  return (
    <section className={styles.card} style={{ display: 'block' }}>
      <h3 style={{ margin: '0 0 0.5rem' }}>Remote URL updates</h3>
      <p className={styles.sub}>
        For a feed whose {FIELD[source.kind] ?? 'URL'} keeps changing: another system can push the
        new one to tvtimes with a token that works for this source only. Only the URL is replaced —
        any login details are kept — and the source refreshes in place. Pushing the URL it already
        has does nothing, so it&rsquo;s safe to run on a timer.
      </p>

      {token ? (
        <>
          <pre className={styles.sub} style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>
            <code>{example}</code>
          </pre>
          <p className={styles.sub}>
            Copy this now — the token is shown once. Rotating gives a new one and the old one stops
            working.
          </p>
        </>
      ) : enabled ? (
        <p className={styles.sub}>
          On · token created {fmt(source.update_token_set_at)} · last used{' '}
          {fmt(source.update_token_last_used_at)}. Send{' '}
          <code>POST {hookUrl(window.location.origin)}</code> with{' '}
          <code>Authorization: Bearer &lt;token&gt;</code> and <code>{'{"url": "…"}'}</code>.
        </p>
      ) : null}

      <div className={styles.toolbar} style={{ marginTop: '0.75rem', gap: '0.5rem' }}>
        <button
          type="button"
          className={`${styles.btn} ${styles.primary}`}
          onClick={generate}
          disabled={busy}
        >
          {busy ? 'Working…' : enabled ? 'Rotate token' : 'Create update token'}
        </button>
        {token ? (
          <button type="button" className={styles.btn} onClick={copy}>
            {copied ? 'Copied' : 'Copy command'}
          </button>
        ) : null}
        {enabled ? (
          <button type="button" className={styles.btn} onClick={disable} disabled={busy}>
            Turn off
          </button>
        ) : null}
      </div>
      {error ? <p className={styles.err}>{error}</p> : null}
    </section>
  );
}
