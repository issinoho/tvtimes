import { useState } from 'react';
import { Link } from 'react-router-dom';

import { AddSourceDialog } from '@/features/sources/AddSourceDialog';
import { StatusPill } from '@/features/sources/StatusPill';
import { useSources } from '@/features/sources/api';
import styles from '@/features/sources/sources.module.css';

export function SourcesPage() {
  const { data: sources, isPending } = useSources();
  const [adding, setAdding] = useState(false);

  return (
    <div className={styles.page}>
      <div className={styles.head}>
        <div>
          <h1>Sources</h1>
          <p>Connect an M3U playlist, an Xtream panel, or a Stalker portal.</p>
        </div>
        <button
          type="button"
          className={`${styles.btn} ${styles.primary}`}
          onClick={() => setAdding(true)}
        >
          Add source
        </button>
      </div>

      {isPending ? (
        <p>Loading…</p>
      ) : !sources || sources.length === 0 ? (
        <p>No sources yet. Add one to start building your guide.</p>
      ) : (
        <ul className={styles.list}>
          {sources.map((s) => (
            <li key={s.id}>
              <Link to={`/sources/${s.id}`} className={styles.card}>
                <div>
                  <h3>
                    <span className={styles.kindTag}>{s.kind}</span>
                    {s.display_name}
                  </h3>
                  <div className={styles.sub}>
                    {s.config_summary}
                    {s.last_status === 'ok' ? ` · ${s.channel_count} channels` : ''}
                    {s.last_status === 'error' && s.last_error ? ` · ${s.last_error}` : ''}
                    {!s.enabled ? ' · disabled' : ''}
                  </div>
                </div>
                <StatusPill status={s.last_status} />
              </Link>
            </li>
          ))}
        </ul>
      )}

      {adding ? <AddSourceDialog onClose={() => setAdding(false)} /> : null}
    </div>
  );
}
