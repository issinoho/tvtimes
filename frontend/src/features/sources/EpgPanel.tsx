import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { StatusPill } from '@/features/sources/StatusPill';
import { api, unwrap } from '@/lib/api/client';
import styles from '@/features/sources/sources.module.css';

const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : 'never');

/** The programme-guide (XMLTV) source(s) attached to one channel source. */
export function EpgPanel({ sourceId }: { sourceId: string }) {
  const qc = useQueryClient();
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
    onSuccess: () => qc.invalidateQueries({ queryKey: ['epg-sources'] }),
  });

  const mine = (epgSources ?? []).filter((s) => s.source_id === sourceId);
  if (mine.length === 0) {
    return (
      <section className={styles.card} style={{ display: 'block' }}>
        <h3 style={{ margin: 0 }}>Programme guide</h3>
        <p className={styles.sub}>
          No XMLTV guide URL was found in this source. Guide data will appear here once a source
          advertises one, or when you attach a standalone XMLTV URL.
        </p>
      </section>
    );
  }

  return (
    <section className={styles.card} style={{ display: 'block' }}>
      <h3 style={{ margin: '0 0 0.5rem' }}>Programme guide</h3>
      {mine.map((s) => (
        <div key={s.id} className={styles.toolbar} style={{ justifyContent: 'space-between' }}>
          <div>
            <div className={styles.sub} style={{ wordBreak: 'break-all' }}>
              {s.url}
            </div>
            <div className={styles.sub}>
              {s.last_status === 'ok' ? `${s.programme_count} programmes · ` : ''}
              fetched {fmt(s.last_fetched_at)}
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
              Refresh guide
            </button>
          </div>
        </div>
      ))}
    </section>
  );
}
