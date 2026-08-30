import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import type { GuideChannel, Programme } from '@/features/guide/api';
import { useGuide } from '@/features/guide/api';
import { GuideAgenda } from '@/features/guide/GuideAgenda';
import { GuideGrid } from '@/features/guide/GuideGrid';
import { ProgrammeSheet } from '@/features/guide/ProgrammeSheet';
import { defaultWindowStart, WINDOW_MINUTES } from '@/features/guide/time';
import { useMediaQuery } from '@/features/guide/useMediaQuery';
import { useSources } from '@/features/sources/api';
import { useAuth } from '@/lib/auth/AuthProvider';
import styles from '@/features/guide/guide.module.css';

const HALF_DAY = WINDOW_MINUTES * 60_000;

export function GuidePage() {
  const { user } = useAuth();
  const isMobile = useMediaQuery('(max-width: 760px)');

  const [windowStart, setWindowStart] = useState(() => defaultWindowStart());
  const [sourceId, setSourceId] = useState('');
  const [group, setGroup] = useState('');
  const [search, setSearch] = useState('');
  const [open, setOpen] = useState<{ channel: GuideChannel; programme: Programme } | null>(null);

  const { data: sources } = useSources();
  const windowEnd = new Date(windowStart.getTime() + HALF_DAY);
  const guide = useGuide({
    from: windowStart.toISOString(),
    to: windowEnd.toISOString(),
    source_id: sourceId || undefined,
    group: group || undefined,
  });

  const allChannels = useMemo(() => guide.data?.channels ?? [], [guide.data]);
  const groups = useMemo(
    () => [...new Set(allChannels.map((c) => c.group_title).filter(Boolean))].sort() as string[],
    [allChannels],
  );
  const channels = useMemo(() => {
    const q = search.trim().toLowerCase();
    return q ? allChannels.filter((c) => c.name.toLowerCase().includes(q)) : allChannels;
  }, [allChannels, search]);

  const shift = (ms: number) => setWindowStart((d) => new Date(d.getTime() + ms));
  const dayLabel = windowStart.toLocaleDateString([], {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  });

  return (
    <div className={styles.page}>
      {user && !user.email_verified ? (
        <p className={styles.verifyBanner}>
          Your email isn’t verified yet — check your inbox for the confirmation link.
        </p>
      ) : null}

      <div className={styles.toolbar}>
        <button type="button" className={styles.btn} onClick={() => shift(-3 * 3_600_000)}>
          ‹
        </button>
        <span className={styles.dateLabel}>{dayLabel}</span>
        <button type="button" className={styles.btn} onClick={() => shift(3 * 3_600_000)}>
          ›
        </button>
        <button
          type="button"
          className={`${styles.btn} ${styles.accent}`}
          onClick={() => setWindowStart(defaultWindowStart())}
        >
          Now
        </button>

        <div className={styles.spacer} />

        <select
          className={styles.select}
          value={sourceId}
          onChange={(e) => setSourceId(e.target.value)}
          aria-label="Source"
        >
          <option value="">All sources</option>
          {(sources ?? []).map((s) => (
            <option key={s.id} value={s.id}>
              {s.display_name}
            </option>
          ))}
        </select>
        <select
          className={styles.select}
          value={group}
          onChange={(e) => setGroup(e.target.value)}
          aria-label="Group"
        >
          <option value="">All groups</option>
          {groups.map((g) => (
            <option key={g} value={g}>
              {g}
            </option>
          ))}
        </select>
        <input
          className={styles.search}
          placeholder="Find a channel…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      {guide.isPending ? (
        <p className={styles.empty}>Loading the guide…</p>
      ) : allChannels.length === 0 ? (
        <div className={styles.empty}>
          <p>
            No channels yet. <Link to="/sources">Connect a source</Link> and its guide to fill this
            in.
          </p>
        </div>
      ) : channels.length === 0 ? (
        <div className={styles.empty}>
          <p>No channels match “{search}”.</p>
        </div>
      ) : isMobile ? (
        <GuideAgenda
          channels={channels}
          onOpen={(channel, programme) => setOpen({ channel, programme })}
        />
      ) : (
        <GuideGrid
          channels={channels}
          windowStart={windowStart}
          onOpen={(channel, programme) => setOpen({ channel, programme })}
        />
      )}

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
