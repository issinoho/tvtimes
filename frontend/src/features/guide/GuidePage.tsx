import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import { useFavourites } from '@/features/favourites/api';
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
  const [favOnly, setFavOnly] = useState(false);
  const [open, setOpen] = useState<{ channel: GuideChannel; programme: Programme } | null>(null);

  const { data: sources } = useSources();
  const { data: favs } = useFavourites();
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
    let list = allChannels;
    if (favOnly && favs) list = list.filter((c) => favs.has(c.id));
    if (q) list = list.filter((c) => c.name.toLowerCase().includes(q));
    return list;
  }, [allChannels, search, favOnly, favs]);

  // Pages within the day, half a window at a time, so the far half of what
  // you were reading becomes the near half.
  const shiftHours = (hours: number) =>
    setWindowStart((d) => new Date(d.getTime() + hours * 3_600_000));

  // A calendar day rather than 24 hours: across a DST change the clock time
  // you were looking at is what you expect to keep, not the elapsed interval.
  const shiftDays = (days: number) =>
    setWindowStart((d) => {
      const next = new Date(d);
      next.setDate(next.getDate() + days);
      return next;
    });

  const zone = allChannels[0]?.timezone;
  const dayLabel = windowStart.toLocaleDateString('en-GB', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    ...(zone ? { timeZone: zone } : {}),
  });
  const time = (d: Date) =>
    d.toLocaleTimeString('en-GB', {
      hour: '2-digit',
      minute: '2-digit',
      ...(zone ? { timeZone: zone } : {}),
    });
  const rangeLabel = `${time(windowStart)}–${time(windowEnd)}`;

  return (
    <div className={styles.page}>
      {user && !user.email_verified ? (
        <p className={styles.verifyBanner}>
          Your email isn’t verified yet — check your inbox for the confirmation link.
        </p>
      ) : null}

      <div className={styles.toolbar}>
        <div className={styles.stepper}>
          <button
            type="button"
            className={styles.btn}
            onClick={() => shiftDays(-1)}
            aria-label="Previous day"
            title="Previous day"
          >
            ‹
          </button>
          <span className={styles.dateLabel}>{dayLabel}</span>
          <button
            type="button"
            className={styles.btn}
            onClick={() => shiftDays(1)}
            aria-label="Next day"
            title="Next day"
          >
            ›
          </button>
        </div>

        <div className={styles.stepper}>
          <button
            type="button"
            className={styles.btn}
            onClick={() => shiftHours(-3)}
            aria-label="Earlier"
            title="Back 3 hours"
          >
            «
          </button>
          <span className={styles.rangeLabel}>{rangeLabel}</span>
          <button
            type="button"
            className={styles.btn}
            onClick={() => shiftHours(3)}
            aria-label="Later"
            title="Forward 3 hours"
          >
            »
          </button>
        </div>
        <button
          type="button"
          className={`${styles.btn} ${styles.accent}`}
          onClick={() => setWindowStart(defaultWindowStart())}
        >
          Now
        </button>

        <button
          type="button"
          className={styles.btn}
          data-active={favOnly || undefined}
          aria-pressed={favOnly}
          onClick={() => setFavOnly((v) => !v)}
          title="Show only favourite channels"
        >
          ★ Favourites
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
          aria-label="Find a channel"
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
          <p>
            {favOnly && (favs?.size ?? 0) === 0
              ? 'No favourite channels yet — tap the star on a channel to add one.'
              : `No channels match “${search}”.`}
          </p>
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
