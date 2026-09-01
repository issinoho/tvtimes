import { useState } from 'react';

import type { GuideChannel, Programme } from '@/features/guide/api';
import { FavStar } from '@/features/favourites/FavStar';
import { GENRE_VAR, genreOf } from '@/features/guide/genre';
import { fmtTime } from '@/features/guide/time';
import { useNow } from '@/features/guide/useNow';
import styles from '@/features/guide/guide.module.css';

interface Props {
  channels: GuideChannel[];
  onOpen: (channel: GuideChannel, programme: Programme) => void;
}

export function GuideAgenda({ channels, onOpen }: Props) {
  const [active, setActive] = useState(0);
  const now = useNow();
  const channel = channels[active];

  return (
    <>
      <div className={styles.chips}>
        {channels.map((c, i) => (
          <button
            key={c.id}
            type="button"
            className={styles.chip}
            data-active={i === active}
            aria-pressed={i === active}
            onClick={() => setActive(i)}
          >
            {c.number ? `${c.number} · ` : ''}
            {c.name}
          </button>
        ))}
      </div>

      {channel ? (
        <div className={styles.agendaHead}>
          <span>
            {channel.number ? `${channel.number} · ` : ''}
            {channel.name}
          </span>
          <FavStar channelId={channel.id} />
        </div>
      ) : null}

      <div className={styles.agenda}>
        {!channel || channel.programmes.length === 0 ? (
          <p style={{ padding: '1rem', color: 'var(--text-dim)' }}>
            No guide data for this channel in this window.
          </p>
        ) : (
          channel.programmes.map((p) => {
            const live = now >= new Date(p.start) && now < new Date(p.stop);
            return (
              <button
                key={p.id}
                type="button"
                className={styles.agendaItem}
                data-now={live}
                style={{ ['--genre' as string]: GENRE_VAR[genreOf(p.categories, p.is_movie)] }}
                onClick={() => onOpen(channel, p)}
              >
                <span className={styles.agendaTime}>{fmtTime(p.start, channel.timezone)}</span>
                <span>
                  <strong style={{ fontWeight: 600 }}>{p.title}</strong>
                  {p.sub_title ? (
                    <span style={{ color: 'var(--text-dim)', fontSize: '0.82rem' }}>
                      {' '}
                      — {p.sub_title}
                    </span>
                  ) : null}
                  {live ? (
                    <span style={{ color: 'var(--now-line)', fontSize: '0.75rem' }}> · on now</span>
                  ) : null}
                </span>
              </button>
            );
          })
        )}
      </div>
    </>
  );
}
