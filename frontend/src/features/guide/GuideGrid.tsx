import { useVirtualizer } from '@tanstack/react-virtual';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import type { GuideChannel, Programme } from '@/features/guide/api';
import { GENRE_VAR, genreOf } from '@/features/guide/genre';
import { fmtTime, hourTicks, ROW_H, trackWidth, WINDOW_MINUTES, xOf } from '@/features/guide/time';
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

export function GuideGrid({ channels, windowStart, onOpen }: Props) {
  const bodyRef = useRef<HTMLDivElement>(null);
  const chanRef = useRef<HTMLDivElement>(null);
  const axisRef = useRef<HTMLDivElement>(null);
  const [focus, setFocus] = useState<Focus | null>(null);
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

  const syncScroll = useCallback(() => {
    const body = bodyRef.current;
    if (!body) return;
    if (chanRef.current) chanRef.current.scrollTop = body.scrollTop;
    if (axisRef.current) {
      axisRef.current.style.transform = `translateX(${-body.scrollLeft}px)`;
    }
    pinLabels();
  }, [pinLabels]);

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
      <div className={styles.corner}>Channel</div>

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
                {ch.logo_url ? (
                  <img className={styles.chanLogo} src={ch.logo_url} alt="" loading="lazy" />
                ) : (
                  <span className={styles.chanLogoEmpty} aria-hidden />
                )}
                <span className={styles.chanName}>{ch.name}</span>
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
        <div className={styles.bodyInner} style={{ width, height: rowVirt.getTotalSize() }}>
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
                      data-focused={focus?.row === vr.index && focus?.col === col}
                      aria-selected={focus?.row === vr.index && focus?.col === col}
                      onClick={() => onOpen(ch, p)}
                      aria-label={`${ch.name}, ${at}, ${p.title}${live ? ', on now' : ''}`}
                      title={p.title}
                    >
                      <span className={styles.cellInner}>
                        <span className={styles.cellTitle}>{p.title}</span>
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
