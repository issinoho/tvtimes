import { useState } from 'react';

import {
  useHighlights,
  useNowNext,
  type Programme,
  type SearchChannel,
  type SearchHit,
} from '@/features/guide/api';
import { ProgrammeSheet } from '@/features/guide/ProgrammeSheet';
import { fmtDayTime, fmtTime } from '@/features/guide/time';
import styles from '@/features/tonight/tonight.module.css';

type Open = { channel: SearchChannel; programme: Programme } | null;

function Logo({ url }: { url: string | null }) {
  return url ? (
    <img className={styles.logo} src={url} alt="" />
  ) : (
    <span className={styles.logoEmpty} />
  );
}

function HitSection({
  heading,
  hits,
  ranked,
  onOpen,
}: {
  heading: string;
  hits: SearchHit[];
  ranked?: boolean;
  onOpen: (o: Open) => void;
}) {
  return (
    <section className={styles.section}>
      <h2 className={styles.heading}>{heading}</h2>
      <div className={styles.rail}>
        {hits.map((h, i) => (
          <button
            key={`${h.channel.id}:${h.programme.id}`}
            type="button"
            className={styles.card}
            onClick={() => onOpen({ channel: h.channel, programme: h.programme })}
          >
            <div className={styles.cardHead}>
              <Logo url={h.channel.logo_url} />
              <span className={styles.channel}>
                {ranked ? <span className={styles.rank}>#{i + 1} · </span> : null}
                {h.channel.name}
              </span>
            </div>
            <span className={styles.now}>
              {h.programme.title}
              {h.programme.year ? ` · ${h.programme.year}` : ''}
            </span>
            <span className={styles.next}>{fmtDayTime(h.programme.start, h.channel.timezone)}</span>
          </button>
        ))}
      </div>
    </section>
  );
}

export function TonightPage() {
  const nowNext = useNowNext();
  const highlights = useHighlights();
  const [open, setOpen] = useState<Open>(null);

  const onAir = (nowNext.data?.channels ?? [])
    .flatMap((r) => (r.current ? [{ ...r, current: r.current }] : []))
    .slice(0, 40);
  const filmsSoon = highlights.data?.films_soon ?? [];
  const topRated = highlights.data?.top_rated ?? [];

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>Tonight</h1>

      <section className={styles.section}>
        <h2 className={styles.heading}>On now</h2>
        {nowNext.isLoading ? null : onAir.length === 0 ? (
          <p className={styles.hint}>
            Nothing on air right now — add a source and its guide data on the Sources page.
          </p>
        ) : (
          <div className={styles.rail}>
            {onAir.map((r) => (
              <button
                key={r.channel.id}
                type="button"
                className={styles.card}
                onClick={() => setOpen({ channel: r.channel, programme: r.current })}
              >
                <div className={styles.cardHead}>
                  <Logo url={r.channel.logo_url} />
                  <span className={styles.channel}>{r.channel.name}</span>
                </div>
                <span className={styles.now}>{r.current.title}</span>
                {r.upcoming ? (
                  <span className={styles.next}>
                    Next: {r.upcoming.title} · {fmtTime(r.upcoming.start, r.channel.timezone)}
                  </span>
                ) : null}
              </button>
            ))}
          </div>
        )}
      </section>

      {filmsSoon.length > 0 ? (
        <HitSection heading="Films on soon" hits={filmsSoon} onOpen={setOpen} />
      ) : null}

      {topRated.length > 0 ? (
        <HitSection heading="Top rated this week" hits={topRated} ranked onOpen={setOpen} />
      ) : null}

      {!highlights.isLoading && filmsSoon.length === 0 && topRated.length === 0 ? (
        <p className={styles.hint}>
          Film highlights appear once your guide has upcoming films (and TMDB is connected in
          Settings for ratings).
        </p>
      ) : null}

      {open ? (
        <ProgrammeSheet
          channel={open.channel}
          programme={open.programme}
          onClose={() => setOpen(null)}
        />
      ) : null}
    </div>
  );
}
