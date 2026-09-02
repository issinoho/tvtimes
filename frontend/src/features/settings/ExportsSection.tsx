import { useState } from 'react';

import { api, ApiError, unwrap } from '@/lib/api/client';
import { useAuth } from '@/lib/auth/AuthProvider';
import styles from '@/features/settings/settings.module.css';

type Links = { playlist_url: string; epg_url: string };

/**
 * The same account as a single `tvtimes://` source URL for tvdinner, derived
 * from the playlist link so it carries the same freshly-minted token. tvdinner
 * expands it back into this pair of export feeds itself — see its README.
 * `tvtimess://` for an https deployment, mirroring its xtream/plex schemes.
 */
function tvdinnerUrl(playlistUrl: string): string | null {
  try {
    const url = new URL(playlistUrl);
    const token = url.searchParams.get('token');
    if (!token) return null;
    const scheme = url.protocol === 'https:' ? 'tvtimess' : 'tvtimes';
    // keep a sub-path deployment's base (…/tv/api/exports/playlist.m3u → /tv)
    const basePath = url.pathname.replace(/\/api\/exports\/playlist\.m3u$/, '');
    return `${scheme}://${url.host}${basePath}?token=${encodeURIComponent(token)}`;
  } catch {
    return null;
  }
}

function CopyRow({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
    }
  }
  return (
    <div className={styles.feedRow}>
      <span className={styles.feedLabel}>{label}</span>
      <code className={styles.secret}>{value}</code>
      <button type="button" className={styles.btn} onClick={copy}>
        {copied ? 'Copied' : 'Copy'}
      </button>
    </div>
  );
}

export function ExportsSection() {
  const { user, refreshMe } = useAuth();
  const enabled = Boolean(user?.export_token_set_at);
  const [links, setLinks] = useState<Links | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const tvdinnerLink = links ? tvdinnerUrl(links.playlist_url) : null;

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      const res = unwrap(await api.POST('/api/account/export-token'));
      setLinks({ playlist_url: res.playlist_url, epg_url: res.epg_url });
      await refreshMe();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not generate feed links.');
    } finally {
      setBusy(false);
    }
  }

  async function disable() {
    setBusy(true);
    setError(null);
    try {
      unwrap(await api.DELETE('/api/account/export-token'));
      setLinks(null);
      await refreshMe();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not disable the feeds.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={styles.section}>
      <h2>
        Export feeds
        {enabled ? <span className={styles.badge}>enabled</span> : null}
      </h2>
      <p className={styles.hint}>
        Serve your whole line-up — every enabled source, de-duplicated and with the guide times
        already corrected for each channel&rsquo;s timezone — as a single M3U playlist and XMLTV
        guide. Point Jellyfin, Plex, Emby, TiviMate or Threadfin at the two URLs below, or hand the
        whole line-up to{' '}
        <a
          href="https://github.com/issinoho/tvdinner"
          target="_blank"
          rel="noreferrer noopener"
          className="linkish"
        >
          tvdinner
        </a>{' '}
        in one click. Anyone with a link can read your line-up and stream through it, so treat them
        as secrets.
      </p>

      {links ? (
        <>
          <CopyRow label="M3U playlist" value={links.playlist_url} />
          <CopyRow label="XMLTV guide" value={links.epg_url} />
          {tvdinnerLink ? (
            <div className={styles.feedRow}>
              <span className={styles.feedLabel}>tvdinner</span>
              <code className={styles.secret}>{tvdinnerLink}</code>
              <a className={styles.btn} href={tvdinnerLink}>
                Open in tvdinner
              </a>
            </div>
          ) : null}
          <p className={styles.ok}>
            Copy these now — the token is shown once. Rotate any time to get fresh links (the old
            ones stop working).
          </p>
        </>
      ) : enabled ? (
        <p className={styles.hint}>
          Feeds are enabled. The URLs are only shown once, when generated — rotate below if you need
          them again.
        </p>
      ) : null}

      <div className={styles.actions}>
        <button
          type="button"
          className={`${styles.btn} ${styles.primary}`}
          onClick={generate}
          disabled={busy}
        >
          {busy ? 'Working…' : enabled ? 'Rotate links' : 'Generate feed links'}
        </button>
        {enabled ? (
          <button
            type="button"
            className={`${styles.btn} ${styles.danger}`}
            onClick={disable}
            disabled={busy}
          >
            Disable
          </button>
        ) : null}
      </div>
      {error ? <p className={styles.error}>{error}</p> : null}
    </section>
  );
}
