import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';

import { AddSourceDialog } from '@/features/sources/AddSourceDialog';
import { StatusPill } from '@/features/sources/StatusPill';
import { useReorderSources, useSources, type SourceOut } from '@/features/sources/api';
import styles from '@/features/sources/sources.module.css';

export function SourcesPage() {
  const { data: sources, isPending } = useSources();
  const reorder = useReorderSources();
  const [adding, setAdding] = useState(false);

  // Local id order for live drag feedback; re-synced from the server list when
  // not mid-drag.
  const [order, setOrder] = useState<string[]>([]);
  const dragId = useRef<string | null>(null);
  const serverOrder = useMemo(() => (sources ?? []).map((s) => s.id), [sources]);

  useEffect(() => {
    if (!dragId.current) setOrder(serverOrder);
  }, [serverOrder]);

  const byId = useMemo(() => {
    const m = new Map<string, SourceOut>();
    for (const s of sources ?? []) m.set(s.id, s);
    return m;
  }, [sources]);
  const rows = order.map((id) => byId.get(id)).filter((s): s is SourceOut => Boolean(s));

  function onDragOver(e: React.DragEvent, overId: string) {
    e.preventDefault();
    const from = dragId.current;
    if (!from || from === overId) return;
    setOrder((cur) => {
      const next = cur.filter((id) => id !== from);
      next.splice(next.indexOf(overId), 0, from);
      return next;
    });
  }

  function onDrop() {
    dragId.current = null;
    if (order.length && order.join() !== serverOrder.join()) reorder.mutate(order);
  }

  return (
    <div className={styles.page}>
      <div className={styles.head}>
        <div>
          <h1>Sources</h1>
          <p>
            Connect an M3U playlist, an Xtream panel, a Stalker portal or an HDHomeRun. Drag to set
            the order they appear in the guide.
          </p>
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
      ) : rows.length === 0 ? (
        <p>No sources yet. Add one to start building your guide.</p>
      ) : (
        <ul className={styles.list}>
          {rows.map((s) => (
            <li
              key={s.id}
              draggable
              onDragStart={() => {
                dragId.current = s.id;
              }}
              onDragOver={(e) => onDragOver(e, s.id)}
              onDrop={onDrop}
              onDragEnd={onDrop}
              data-dragging={dragId.current === s.id}
              className={styles.row}
            >
              <span className={styles.grip} aria-hidden title="Drag to reorder">
                ⠿
              </span>
              <Link to={`/sources/${s.id}`} className={styles.card} draggable={false}>
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
