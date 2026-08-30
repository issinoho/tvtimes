import { useEffect } from 'react';

import type { GuideChannel, Programme } from '@/features/guide/api';
import { GENRE_VAR, genreOf } from '@/features/guide/genre';
import { fmtDayTime } from '@/features/guide/time';
import { useHero } from '@/features/guide/hero';
import { useDialogFocus } from '@/lib/useDialogFocus';
import styles from '@/features/guide/guide.module.css';

interface Props {
  channel: GuideChannel;
  programme: Programme;
  onClose: () => void;
}

export function ProgrammeSheet({ channel, programme, onClose }: Props) {
  const { data: hero } = useHero(programme.id);
  const sheetRef = useDialogFocus<HTMLElement>();

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
  const fmt = (d: Date) => fmtDayTime(d, channel.timezone);

  const e = hero?.enrichment ?? null;
  const genre = genreOf(programme.categories, programme.is_movie);
  const description = e?.overview ?? programme.description;
  const genreList = e?.genres.length ? e.genres : programme.categories;
  const year = e?.release_year ?? programme.year;

  return (
    <>
      <div className={styles.sheetBackdrop} onClick={onClose} />
      <aside
        ref={sheetRef}
        className={styles.sheet}
        style={{ ['--genre' as string]: GENRE_VAR[genre] }}
        role="dialog"
        aria-modal="true"
        aria-label={programme.title}
        tabIndex={-1}
      >
        <button type="button" className={`${styles.btn} ${styles.close}`} onClick={onClose}>
          Close
        </button>

        {e?.backdrop_url ? (
          <div
            className={styles.heroArt}
            style={{ backgroundImage: `url(${e.backdrop_url})` }}
            aria-hidden
          >
            {e.logo_url ? <img className={styles.heroLogo} src={e.logo_url} alt="" /> : null}
          </div>
        ) : null}

        <p className={styles.kv}>{channel.name}</p>
        <h2>{programme.title}</h2>
        {programme.sub_title ? <p className={styles.kv}>{programme.sub_title}</p> : null}
        {e?.tagline ? <p className={styles.tagline}>{e.tagline}</p> : null}

        <p className={styles.when}>
          {fmt(start)} – {fmt(stop)}
          {year ? ` · ${year}` : ''}
          {e?.runtime ? ` · ${e.runtime} min` : ''}
          {live ? ' · on now' : ''}
        </p>
        {live ? (
          <div className={styles.progress}>
            <span style={{ width: `${pct}%` }} />
          </div>
        ) : null}

        {e?.rating != null ? (
          <p className={styles.rating}>
            ★ {e.rating.toFixed(1)}
            <span className={styles.attribution}> · TMDB</span>
          </p>
        ) : null}

        {genreList.length ? (
          <div className={styles.chipRow}>
            {genreList.map((c) => (
              <span key={c} className={styles.gchip}>
                {c}
              </span>
            ))}
          </div>
        ) : null}

        {programme.episode_num ? (
          <p className={styles.kv}>Episode {programme.episode_num}</p>
        ) : null}
        {e?.director ? <p className={styles.kv}>Directed by {e.director}</p> : null}
        {e?.cast.length ? (
          <p className={styles.kv}>
            {e.cast
              .slice(0, 6)
              .map((c) => c.name)
              .join(', ')}
          </p>
        ) : null}

        {description ? (
          <p className={styles.desc}>{description}</p>
        ) : (
          <p className={styles.kv}>No description in this guide.</p>
        )}

        {hero?.enriching ? (
          <p className={styles.kv} style={{ marginTop: '1rem' }}>
            Fetching artwork and details from TMDB…
          </p>
        ) : null}
        {hero && !hero.tmdb_connected ? (
          <p className={styles.kv} style={{ marginTop: '1rem' }}>
            Add a TMDB key in Settings for backdrops, cast and ratings.
          </p>
        ) : null}
      </aside>
    </>
  );
}
