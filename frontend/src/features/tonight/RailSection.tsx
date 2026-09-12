import { Children, useCallback, useEffect, useRef, useState, type ReactNode } from 'react';

import { useMediaQuery } from '@/features/guide/useMediaQuery';
import styles from '@/features/tonight/tonight.module.css';

/**
 * How far one arrow press moves the rail: just under a viewport, so a card
 * stays on screen as an anchor rather than the whole row teleporting. The
 * rail's `scroll-snap` tidies up where it lands.
 */
const PAGE_FRACTION = 0.85;

/** Sub-pixel layout means scrollLeft never lands exactly on 0 or on the max. */
const EDGE_SLACK = 1;

type Reach = { left: boolean; right: boolean };

/**
 * A heading, optional control, and a horizontally-scrolling rail of cards --
 * with arrow buttons that scroll it.
 *
 * The arrows are there for remotes. On a Fire TV Stick (tvtimes in Silk, see
 * docs/homelab.md) there is no pointer, no wheel and no touch, so a rail that
 * overflows is simply unreachable past its first screenful: the only way to
 * move it was to drag a scrollbar that device can't aim at. A d-pad *can*
 * land on a button, so the scroll gets a button.
 *
 * They are only drawn when the rail actually overflows -- a three-card rail on
 * a desktop has nowhere to go, and arrows for it would be noise.
 */
export function RailSection({
  heading,
  control,
  note,
  children,
}: {
  heading: string;
  /** Extra control for the heading row, left of the arrows (e.g. a filter toggle). */
  control?: ReactNode;
  /** Rendered instead of the rail, for an empty state. */
  note?: ReactNode;
  children?: ReactNode;
}) {
  const railRef = useRef<HTMLDivElement>(null);
  const [reach, setReach] = useState<Reach>({ left: false, right: false });
  const still = useMediaQuery('(prefers-reduced-motion: reduce)');

  const sync = useCallback(() => {
    const el = railRef.current;
    if (!el) return;
    const max = el.scrollWidth - el.clientWidth;
    setReach((prev) => {
      const left = el.scrollLeft > EDGE_SLACK;
      const right = el.scrollLeft < max - EDGE_SLACK;
      // Same object when nothing moved, so the render-effect below can't loop.
      return prev.left === left && prev.right === right ? prev : { left, right };
    });
  }, []);

  useEffect(() => {
    const el = railRef.current;
    if (!el) return;
    el.addEventListener('scroll', sync, { passive: true });
    const observer = new ResizeObserver(sync);
    observer.observe(el);
    return () => {
      el.removeEventListener('scroll', sync);
      observer.disconnect();
    };
  }, [sync]);

  // Deliberately every render, not just on mount: the cards arrive from a
  // query, and a rail that grows from empty to overflowing changes only its
  // scrollWidth -- which no scroll event and no ResizeObserver reports.
  useEffect(sync);

  const scrollByPage = (direction: 1 | -1) => {
    const el = railRef.current;
    if (!el) return;
    el.scrollBy({
      left: direction * el.clientWidth * PAGE_FRACTION,
      behavior: still ? 'auto' : 'smooth',
    });
  };

  const scrollable = reach.left || reach.right;
  const hasCards = Children.count(children) > 0;

  // aria-disabled rather than disabled, because a disabled button drops focus,
  // and a remote that loses focus at the end of a rail has to start its whole
  // d-pad walk again. The button stays focusable and the press just no-ops.
  const arrow = (direction: 1 | -1, glyph: string, label: string) => {
    const live = direction === 1 ? reach.right : reach.left;
    return (
      <button
        type="button"
        className={styles.railBtn}
        aria-disabled={!live}
        aria-label={`${label} ${heading}`}
        title={`${label} ${heading}`}
        onClick={() => live && scrollByPage(direction)}
      >
        {glyph}
      </button>
    );
  };

  return (
    <section className={styles.section}>
      <div className={styles.sectionHead}>
        <h2 className={styles.heading}>{heading}</h2>
        <div className={styles.headControls}>
          {control}
          {scrollable ? (
            <div className={styles.railNav}>
              {arrow(-1, '‹', 'Scroll back through')}
              {arrow(1, '›', 'Scroll forward through')}
            </div>
          ) : null}
        </div>
      </div>
      {note ??
        (hasCards ? (
          <div
            ref={railRef}
            className={styles.rail}
            // Named so a screen reader announces the row as one thing rather
            // than a loose run of buttons -- and so the arrows' own labels
            // ("Scroll forward through Films on soon") name what they move.
            role="group"
            aria-label={heading}
          >
            {children}
          </div>
        ) : null)}
    </section>
  );
}
