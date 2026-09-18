import { useVirtualizer } from '@tanstack/react-virtual';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { GuideChannel, Programme } from '@/features/guide/api';
import { ChannelLogo } from '@/features/guide/ChannelLogo';
import { FavStar } from '@/features/favourites/FavStar';
import { GENRE_VAR, genreOf } from '@/features/guide/genre';
import { fmtTime, hourTicks, ROW_H, trackWidth, WINDOW_MINUTES, xOf } from '@/features/guide/time';
import { useMediaQuery } from '@/features/guide/useMediaQuery';
import { useNow } from '@/features/guide/useNow';
import styles from '@/features/guide/guide.module.css';

interface Props {
  channels: GuideChannel[];
  windowStart: Date;
  onOpen: (channel: GuideChannel, programme: Programme) => void;
}

interface Focus {
  row: number;
  col: number;
}

type Reach = { up: boolean; down: boolean };

/** Sub-pixel layout means scrollTop never lands exactly on 0 or on the max. */
const EDGE_SLACK = 1;

/**
 * How far one ▲/▼ press moves the grid: just under a screenful, in whole
 * rows, so the last channel you could see is still there as an anchor and no
 * row lands half-cut at the top.
 */
function pageRows(clientHeight: number) {
  return Math.max(1, Math.floor((clientHeight * 0.85) / ROW_H));
}

export function GuideGrid({ channels, windowStart, onOpen }: Props) {
  const bodyRef = useRef<HTMLDivElement>(null);
  const chanRef = useRef<HTMLDivElement>(null);
  const axisRef = useRef<HTMLDivElement>(null);
  const innerRef = useRef<HTMLDivElement>(null);
  const [focus, setFocus] = useState<Focus | null>(null);
  const [reach, setReach] = useState<Reach>({ up: false, down: false });
  const still = useMediaQuery('(prefers-reduced-motion: reduce)');
  const now = useNow();

  const width = trackWidth();
  const axisTz = channels[0]?.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone;
  const ticks = useMemo(() => hourTicks(windowStart, axisTz), [windowStart, axisTz]);

  const rowVirt = useVirtualizer({
    count: channels.length,
    getScrollElement: () => bodyRef.current,
    estimateSize: () => ROW_H,
    overscan: 8,
    // Seed a viewport so rows render before the first real layout measurement
    // (also lets the grid render under jsdom, which never lays out).
    initialRect: { width: 1200, height: 800 },
  });

  // Keep each programme's label visible while the guide is scrolled through a
  // wide cell: slide the label right by however far the cell's start is past
  // the left edge, capped so it never overruns the cell.
  const pinLabels = useCallback(() => {
    const body = bodyRef.current;
    if (!body) return;
    const sl = body.scrollLeft;
    // Read all geometry first, then write, to avoid layout thrash.
    const plan: { inner: HTMLElement; shift: number }[] = [];
    for (const cell of body.querySelectorAll<HTMLElement>('[data-cell]')) {
      const inner = cell.firstElementChild as HTMLElement | null;
      if (!inner) continue;
      plan.push({
        inner,
        shift: Math.min(
          Math.max(0, sl - cell.offsetLeft),
          Math.max(0, cell.offsetWidth - inner.offsetWidth - 6),
        ),
      });
    }
    for (const { inner, shift } of plan) {
      inner.style.transform = shift ? `translateX(${shift}px)` : '';
    }
  }, []);

  const syncReach = useCallback(() => {
    const body = bodyRef.current;
    if (!body) return;
    const max = body.scrollHeight - body.clientHeight;
    const up = body.scrollTop > EDGE_SLACK;
    const down = body.scrollTop < max - EDGE_SLACK;
    // Same object when nothing moved, so a no-op observation is a no-op render.
    setReach((prev) => (prev.up === up && prev.down === down ? prev : { up, down }));
  }, []);

  const syncScroll = useCallback(() => {
    const body = bodyRef.current;
    if (!body) return;
    if (chanRef.current) chanRef.current.scrollTop = body.scrollTop;
    if (axisRef.current) {
      axisRef.current.style.transform = `translateX(${-body.scrollLeft}px)`;
    }
    pinLabels();
    syncReach();
  }, [pinLabels, syncReach]);

  // Two things move the reach without a scroll: the grid is resized, or a
  // filter changes how many channels it holds -- which resizes the inner
  // track, not the box. ResizeObserver also fires once on observe(), which
  // takes the first measurement.
  useEffect(() => {
    const body = bodyRef.current;
    const inner = innerRef.current;
    if (!body || !inner) return;
    const resize = new ResizeObserver(syncReach);
    resize.observe(body);
    resize.observe(inner);
    return () => resize.disconnect();
  }, [syncReach]);

  /**
   * The ▲/▼ buttons are there for remotes. Silk on a Fire TV Stick drives the
   * page with a cursor, and at the screen edge that cursor scrolls the
   * *document* -- which never moves here, because the rows scroll inside
   * `.body`. There is no wheel, no touch and no scrollbar it can drag, so
   * past the first screenful of channels the guide was unreachable. A cursor
   * (or a d-pad) can always land on a button. Same answer as the Tonight
   * rails' arrows (RailSection.tsx).
   */
  const scrollByPage = (direction: 1 | -1) => {
    const body = bodyRef.current;
    if (!body) return;
    const row = Math.round(body.scrollTop / ROW_H) + direction * pageRows(body.clientHeight);
    body.scrollTo({ top: Math.max(0, row * ROW_H), behavior: still ? 'auto' : 'smooth' });
  };

  // aria-disabled rather than disabled: a disabled button drops focus, which
  // strands a d-pad walk at the top or bottom of the list.
  const pager = (direction: 1 | -1, glyph: string, label: string) => {
    const live = direction === 1 ? reach.down : reach.up;
    return (
      <button
        type="button"
        className={styles.pageBtn}
        aria-disabled={!live}
        aria-label={label}
        title={label}
        onClick={() => live && scrollByPage(direction)}
      >
        {glyph}
      </button>
    );
  };

  // Centre on "now" — on first mount and whenever the window is re-anchored
  // (the "Now" button, day nav). Reads the clock directly so the 30s `now`
  // tick doesn't yank the scroll position.
  useEffect(() => {
    const body = bodyRef.current;
    if (!body) return;
    const x = xOf(windowStart, new Date());
    if (x > 0 && x < width) body.scrollLeft = Math.max(0, x - body.clientWidth / 3);
    pinLabels();
  }, [windowStart, width, pinLabels]);

  // Re-pin after the virtualiser (re)renders rows.
  useEffect(pinLabels);

  const nowX = xOf(windowStart, now);
  const showNow = nowX >= 0 && nowX <= width;

  function move(dRow: number, dCol: number) {
    setFocus((f) => {
      const row = Math.min(channels.length - 1, Math.max(0, (f?.row ?? 0) + dRow));
      const list = channels[row]?.programmes ?? [];
      if (!list.length) return { row, col: 0 };
      let col: number;
      if (f && dRow !== 0) {
        // keep roughly the same time when moving between channels
        const cur = channels[f.row]?.programmes[f.col];
        const anchor = cur ? new Date(cur.start).getTime() : now.getTime();
        col = Math.max(
          0,
          list.findIndex((p) => new Date(p.stop).getTime() > anchor),
        );
      } else {
        col = Math.min(list.length - 1, Math.max(0, (f?.col ?? 0) + dCol));
      }
      rowVirt.scrollToIndex(row, { align: 'auto' });
      return { row, col };
    });
  }

  function onKeyDown(e: React.KeyboardEvent) {
    switch (e.key) {
      case 'ArrowRight':
        e.preventDefault();
        move(0, 1);
        break;
      case 'ArrowLeft':
        e.preventDefault();
        move(0, -1);
        break;
      case 'ArrowDown':
        e.preventDefault();
        move(1, 0);
        break;
      case 'ArrowUp':
        e.preventDefault();
        move(-1, 0);
        break;
      case 'PageDown':
        e.preventDefault();
        move(8, 0);
        break;
      case 'PageUp':
        e.preventDefault();
        move(-8, 0);
        break;
      case 'Home': {
        e.preventDefault();
        bodyRef.current?.scrollTo({ left: Math.max(0, nowX - 200) });
        setFocus({ row: focus?.row ?? 0, col: 0 });
        break;
      }
      case 'Enter':
      case ' ': {
        if (focus) {
          const ch = channels[focus.row];
          const p = ch?.programmes[focus.col];
          if (ch && p) {
            e.preventDefault();
            onOpen(ch, p);
          }
        }
        break;
      }
    }
  }

  return (
    <div className={styles.gridWrap}>
      <div className={styles.corner}>
        <span>Channel</span>
        {reach.up || reach.down ? (
          <div className={styles.pageNav}>
            {pager(-1, '▲', 'Previous channels')}
            {pager(1, '▼', 'More channels')}
          </div>
        ) : null}
      </div>

      <div className={styles.axis} ref={axisRef}>
        <div className={styles.axisInner} style={{ width }}>
          {ticks.map((t) => (
            <div key={t.x} className={styles.tick} style={{ left: t.x }}>
              {t.label}
            </div>
          ))}
        </div>
      </div>

      <div className={styles.chanPane} ref={chanRef}>
        <div className={styles.chanInner} style={{ height: rowVirt.getTotalSize() }}>
          {rowVirt.getVirtualItems().map((vr) => {
            const ch = channels[vr.index];
            return (
              <div
                key={ch.id}
                className={styles.chanCell}
                style={{ top: vr.start, height: vr.size }}
              >
                <span className={styles.chanNum}>{ch.number ?? ''}</span>
                <ChannelLogo
                  channelId={ch.id}
                  hasLogo={Boolean(ch.logo_url)}
                  imgClassName={styles.chanLogo}
                  emptyClassName={styles.chanLogoEmpty}
                />
                <span className={styles.chanName}>{ch.name}</span>
                <FavStar channelId={ch.id} />
              </div>
            );
          })}
        </div>
      </div>

      <div
        className={styles.body}
        ref={bodyRef}
        onScroll={syncScroll}
        onKeyDown={onKeyDown}
        tabIndex={0}
        role="grid"
        aria-label="TV guide"
      >
        <div
          ref={innerRef}
          className={styles.bodyInner}
          style={{ width, height: rowVirt.getTotalSize() }}
        >
          {showNow ? <div className={styles.nowLine} style={{ left: nowX }} /> : null}
          {rowVirt.getVirtualItems().map((vr) => {
            const ch = channels[vr.index];
            return (
              <div
                key={ch.id}
                className={styles.row}
                style={{ top: vr.start, height: vr.size }}
                role="row"
                aria-label={ch.name}
              >
                {ch.programmes.map((p, col) => {
                  const left = Math.max(0, xOf(windowStart, new Date(p.start)));
                  const right = Math.min(width, xOf(windowStart, new Date(p.stop)));
                  const w = right - left;
                  if (w < 2) return null;
                  const live = now >= new Date(p.start) && now < new Date(p.stop);
                  const at = fmtTime(p.start, ch.timezone);
                  return (
                    <button
                      key={p.id}
                      type="button"
                      role="gridcell"
                      className={styles.cell}
                      style={{
                        left,
                        width: w,
                        ['--genre' as string]: GENRE_VAR[genreOf(p.categories, p.is_movie)],
                      }}
                      data-cell
                      data-now={live}
                      data-watched={p.watched}
                      data-focused={focus?.row === vr.index && focus?.col === col}
                      aria-selected={focus?.row === vr.index && focus?.col === col}
                      onClick={() => onOpen(ch, p)}
                      aria-label={`${ch.name}, ${at}, ${p.title}${live ? ', on now' : ''}${
                        p.watched ? ', watched' : ''
                      }`}
                      title={p.title}
                    >
                      <span className={styles.cellInner}>
                        <span className={styles.cellTitle}>
                          {p.watched ? (
                            <span className={styles.watchedMark} aria-hidden>
                              ✓
                            </span>
                          ) : null}
                          {p.title}
                        </span>
                        <span className={styles.cellMeta}>
                          {at}
                          {p.is_movie && p.year ? ` · ${p.year}` : ''}
                        </span>
                      </span>
                    </button>
                  );
                })}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export const GUIDE_WINDOW_MINUTES = WINDOW_MINUTES;
