import { useEffect } from 'react';

import type { GuideChannel, Programme } from '@/features/guide/api';
import { GENRE_VAR, genreOf } from '@/features/guide/genre';
import styles from '@/features/guide/guide.module.css';

interface Props {
  channel: GuideChannel;
  programme: Programme;
  onClose: () => void;
}

export function ProgrammeSheet({ channel, programme, onClose }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const start = new Date(programme.start);
  const stop = new Date(programme.stop);
  const now = Date.now();
  const live = now >= start.getTime() && now < stop.getTime();
  const pct = live
    ? Math.round(((now - start.getTime()) / (stop.getTime() - start.getTime())) * 100)
    : 0;
  const fmt = (d: Date) =>
    d.toLocaleString([], { weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false });
  const genre = genreOf(programme.categories, programme.is_movie);

  return (
    <>
      <div className={styles.sheetBackdrop} onClick={onClose} />
      <aside
        className={styles.sheet}
        style={{ ['--genre' as string]: GENRE_VAR[genre] }}
        role="dialog"
        aria-label={programme.title}
      >
        <button type="button" className={`${styles.btn} ${styles.close}`} onClick={onClose}>
          Close
        </button>
        <p className={styles.kv}>{channel.name}</p>
        <h2>{programme.title}</h2>
        {programme.sub_title ? <p className={styles.kv}>{programme.sub_title}</p> : null}
        <p className={styles.when}>
          {fmt(start)} – {fmt(stop)}
          {programme.year ? ` · ${programme.year}` : ''}
          {live ? ' · on now' : ''}
        </p>
        {live ? (
          <div className={styles.progress}>
            <span style={{ width: `${pct}%` }} />
          </div>
        ) : null}

        {programme.categories.length ? (
          <div className={styles.chipRow}>
            {programme.categories.map((c) => (
              <span key={c} className={styles.gchip}>
                {c}
              </span>
            ))}
          </div>
        ) : null}

        {programme.episode_num ? (
          <p className={styles.kv}>Episode {programme.episode_num}</p>
        ) : null}
        {programme.director ? <p className={styles.kv}>Directed by {programme.director}</p> : null}
        {programme.description ? (
          <p className={styles.desc}>{programme.description}</p>
        ) : (
          <p className={styles.kv}>No description in this guide.</p>
        )}
        <p className={styles.kv} style={{ marginTop: '1rem' }}>
          Richer detail — artwork, cast, ratings — arrives with TMDB enrichment.
        </p>
      </aside>
    </>
  );
}
