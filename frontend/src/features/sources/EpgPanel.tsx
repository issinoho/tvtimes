import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { StatusPill } from '@/features/sources/StatusPill';
import { api, ApiError, unwrap } from '@/lib/api/client';
import styles from '@/features/sources/sources.module.css';

const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : 'never');

/** A short label for one advertised feed: the file name, which is what tells
 * them apart (they usually share a host and directory). */
function feedLabel(url: string): string {
  try {
    const last = new URL(url).pathname.split('/').filter(Boolean).pop();
    return last ? decodeURIComponent(last) : url;
  } catch {
    return url;
  }
}

/** The XMLTV guide source(s) feeding this channel source — the one discovered
 * from the playlist, any standalone URL attached here (which matches only this
 * source's channels), and any tenant-wide one attached before scoping existed. */
export function EpgPanel({
  sourceId,
  advertised = [],
}: {
  sourceId: string;
  /** Guide URLs the playlist lists when it lists several — none of them is
   * attached automatically, so they're offered here to pick from. */
  advertised?: string[];
}) {
  const qc = useQueryClient();
  const [url, setUrl] = useState('');
  const [picked, setPicked] = useState('');
  const [error, setError] = useState<string | null>(null);

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['epg-sources'] });
    void qc.invalidateQueries({ queryKey: ['guide'] });
  };

  const { data: epgSources } = useQuery({
    queryKey: ['epg-sources'],
    queryFn: async () => unwrap(await api.GET('/api/epg-sources')),
    refetchInterval: (q) =>
      (q.state.data ?? []).some((s) => s.last_status === 'pending') ? 3000 : false,
  });

  const refresh = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST('/api/epg-sources/{epg_source_id}/refresh', {
          params: { path: { epg_source_id: id } },
        }),
      ),
    onSuccess: invalidate,
  });

  const attach = useMutation({
    mutationFn: async (u: string) =>
      unwrap(await api.POST('/api/epg-sources', { body: { url: u, scope_source_id: sourceId } })),
    onSuccess: () => {
      setUrl('');
      setPicked('');
      setError(null);
      invalidate();
    },
    onError: (e) =>
      setError(e instanceof ApiError ? e.message : 'Could not attach that XMLTV URL.'),
  });

  const detach = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.DELETE('/api/epg-sources/{epg_source_id}', {
          params: { path: { epg_source_id: id } },
        }),
      ),
    onSuccess: invalidate,
  });

  // The playlist-discovered EPG for this source, standalone URLs attached to
  // it, and unscoped standalone URLs (which apply to every source's channels).
  const mine = (epgSources ?? []).filter(
    (s) =>
      s.source_id === sourceId ||
      s.scope_source_id === sourceId ||
      (s.source_id === null && s.scope_source_id === null),
  );
  const label = (s: (typeof mine)[number]) =>
    s.source_id !== null
      ? 'from the playlist'
      : s.scope_source_id !== null
        ? 'attached here'
        : 'attached · all sources — paste the URL again to limit it to this one';

  const attachedUrls = new Set(mine.map((s) => s.url));
  const offered = advertised.filter((u) => !attachedUrls.has(u));
  // Duplicate file names (same name on two hosts) fall back to the full URL.
  const labels = offered.map(feedLabel);
  const optionLabel = (u: string, i: number) =>
    labels.indexOf(labels[i]) === labels.lastIndexOf(labels[i]) ? labels[i] : u;

  return (
    <section className={styles.card} style={{ display: 'block' }}>
      <h3 style={{ margin: '0 0 0.5rem' }}>Programme guide</h3>

      {mine.length === 0 && offered.length === 0 ? (
        <p className={styles.sub}>
          No XMLTV URL yet. If your playlist doesn’t advertise one, paste it below.
        </p>
      ) : (
        mine.map((s) => (
          <div
            key={s.id}
            className={styles.toolbar}
            style={{ justifyContent: 'space-between', marginBottom: '0.5rem' }}
          >
            <div>
              <div className={styles.sub} style={{ wordBreak: 'break-all' }}>
                {s.url}
              </div>
              <div className={styles.sub}>
                {label(s)}
                {s.last_status === 'ok' ? ` · ${s.programme_count} programmes` : ''}
                {` · fetched ${fmt(s.last_fetched_at)}`}
                {s.last_status === 'error' && s.last_error ? ` · ${s.last_error}` : ''}
              </div>
            </div>
            <div className={styles.toolbar}>
              <StatusPill status={s.last_status} />
              <button
                type="button"
                className={styles.btn}
                onClick={() => refresh.mutate(s.id)}
                disabled={refresh.isPending || s.last_status === 'pending'}
              >
                Refresh
              </button>
              {s.source_id === null ? (
                <button
                  type="button"
                  className={styles.btn}
                  onClick={() => detach.mutate(s.id)}
                  disabled={detach.isPending}
                >
                  Remove
                </button>
              ) : null}
            </div>
          </div>
        ))
      )}

      {offered.length > 0 ? (
        <form
          className={styles.toolbar}
          style={{ marginTop: '0.75rem', gap: '0.5rem', flexWrap: 'wrap' }}
          onSubmit={(e) => {
            e.preventDefault();
            if (picked) attach.mutate(picked);
          }}
        >
          <p className={styles.sub} style={{ flexBasis: '100%', margin: 0 }}>
            Your playlist lists {advertised.length} guide feeds, so none was attached automatically.
            Pick the one that covers these channels.
          </p>
          <select
            value={picked}
            onChange={(e) => setPicked(e.target.value)}
            aria-label="Guide feed from the playlist"
            style={{ flex: 1, minWidth: 0 }}
          >
            <option value="">Choose a feed…</option>
            {offered.map((u, i) => (
              <option key={u} value={u}>
                {optionLabel(u, i)}
              </option>
            ))}
          </select>
          <button
            type="submit"
            className={`${styles.btn} ${styles.primary}`}
            disabled={attach.isPending || !picked}
          >
            Attach feed
          </button>
          {picked ? (
            <p
              className={styles.sub}
              style={{ flexBasis: '100%', margin: 0, wordBreak: 'break-all' }}
            >
              {picked}
            </p>
          ) : null}
        </form>
      ) : null}

      <form
        className={styles.toolbar}
        style={{ marginTop: '0.75rem', gap: '0.5rem' }}
        onSubmit={(e) => {
          e.preventDefault();
          if (url.trim()) attach.mutate(url.trim());
        }}
      >
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://…/epg.xml  (or .xml.gz)"
          aria-label="XMLTV guide URL"
          style={{ flex: 1, minWidth: 0 }}
        />
        <button
          type="submit"
          className={`${styles.btn} ${styles.primary}`}
          disabled={attach.isPending || !url.trim()}
        >
          {attach.isPending ? 'Attaching…' : 'Attach XMLTV'}
        </button>
      </form>
      {error ? <p className={styles.err}>{error}</p> : null}
    </section>
  );
}
