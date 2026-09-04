import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';

import { AddSourceDialog } from '@/features/sources/AddSourceDialog';
import { StatusPill } from '@/features/sources/StatusPill';
import { useReorderSources, useSources, type SourceOut } from '@/features/sources/api';
import { timeAgo } from '@/features/sources/relativeTime';
import styles from '@/features/sources/sources.module.css';

export function SourcesPage() {
  const { data: sources, isPending } = useSources();
  const reorder = useReorderSources();
  const [adding, setAdding] = useState(false);

  // Local id order for live drag feedback; re-synced from the server list when
  // not mid-drag.
  const [order, setOrder] = useState<string[]>([]);
  // The ref is what onDragOver / onDrop / the re-sync effect read: all of
  // those run outside render and need the value synchronously. The state
  // mirrors it purely so the row can dim -- mutating a ref doesn't
  // re-render, so reading dragId.current in the markup meant the dragged
  // row never actually dimmed on pick-up.
  const dragId = useRef<string | null>(null);
  const [draggingId, setDraggingId] = useState<string | null>(null);

  const beginDrag = (id: string) => {
    dragId.current = id;
    setDraggingId(id);
  };
  const endDrag = () => {
    dragId.current = null;
    setDraggingId(null);
  };
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
    endDrag();
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
              onDragStart={() => beginDrag(s.id)}
              onDragOver={(e) => onDragOver(e, s.id)}
              onDrop={onDrop}
              onDragEnd={onDrop}
              data-dragging={draggingId === s.id}
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
                    {s.channel_count ? ` · ${s.channel_count} channels` : ''}
                    {s.last_status === 'error' && s.last_error ? ` · ${s.last_error}` : ''}
                    {!s.enabled ? ' · disabled' : ''}
                  </div>
                  <div className={styles.sub}>
                    {s.epg_status === 'error'
                      ? `guide: error${s.epg_error ? ` — ${s.epg_error}` : ''}`
                      : s.epg_status
                        ? `guide: ${(s.programme_count ?? 0).toLocaleString()} programmes · ${timeAgo(
                            s.epg_last_fetched_at ?? null,
                          )}`
                        : s.epg_url
                          ? 'guide: waiting for the first fetch'
                          : 'no guide feed'}
                    {s.last_refreshed_at
                      ? ` · channels checked ${timeAgo(s.last_refreshed_at)}`
                      : ''}
                  </div>
                </div>
                <StatusPill status={s.health ?? s.last_status} />
              </Link>
            </li>
          ))}
        </ul>
      )}

      {adding ? <AddSourceDialog onClose={() => setAdding(false)} /> : null}
    </div>
  );
}
