import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { StatusPill } from '@/features/sources/StatusPill';
import { api, ApiError, unwrap } from '@/lib/api/client';
import styles from '@/features/sources/sources.module.css';

const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : 'never');

/** The XMLTV guide source(s) feeding this channel source — the one discovered
 * from the playlist, plus any standalone URL you attach here. */
export function EpgPanel({ sourceId }: { sourceId: string }) {
  const qc = useQueryClient();
  const [url, setUrl] = useState('');
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
      unwrap(await api.POST('/api/epg-sources', { body: { url: u } })),
    onSuccess: () => {
      setUrl('');
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

  // The playlist-discovered EPG for this source, plus standalone URLs (which
  // apply to every channel, this source's included).
  const mine = (epgSources ?? []).filter((s) => s.source_id === sourceId || s.source_id === null);

  return (
    <section className={styles.card} style={{ display: 'block' }}>
      <h3 style={{ margin: '0 0 0.5rem' }}>Programme guide</h3>

      {mine.length === 0 ? (
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
                {s.source_id === null ? 'attached · all channels' : 'from the playlist'}
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
