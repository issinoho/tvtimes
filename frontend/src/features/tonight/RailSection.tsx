import { Children, useCallback, useEffect, useState, type ReactNode } from 'react';

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
  // State, not a ref: the rail is only rendered once it has cards, so on the
  // "On now" row it mounts a beat after the section does. A ref wouldn't
  // re-run the effect below when it finally arrived, and the rail would spend
  // the rest of the session with no scroll listener on it.
  const [rail, setRail] = useState<HTMLDivElement | null>(null);
  const [reach, setReach] = useState<Reach>({ left: false, right: false });
  const still = useMediaQuery('(prefers-reduced-motion: reduce)');

  const sync = useCallback(() => {
    setReach((prev) => {
      const max = rail ? rail.scrollWidth - rail.clientWidth : 0;
      const left = rail ? rail.scrollLeft > EDGE_SLACK : false;
      const right = rail ? rail.scrollLeft < max - EDGE_SLACK : false;
      // Same object when nothing moved, so a no-op observation is a no-op render.
      return prev.left === left && prev.right === right ? prev : { left, right };
    });
  }, [rail]);

  // Three things move a rail's reach, and none of them is a render: it is
  // scrolled, it is resized, or its cards change under it (a refetch adds a
  // few, and a rail that grows past its box changes only scrollWidth, which
  // no resize reports). Measuring in the effect body instead would be a
  // synchronous setState in an effect -- cascading renders, and the lint rule
  // that says so is right. ResizeObserver also fires once on observe(), so
  // the first measurement comes from the same path as every later one.
  useEffect(() => {
    if (!rail) return;
    rail.addEventListener('scroll', sync, { passive: true });
    const resize = new ResizeObserver(sync);
    resize.observe(rail);
    const cards = new MutationObserver(sync);
    cards.observe(rail, { childList: true });
    return () => {
      rail.removeEventListener('scroll', sync);
      resize.disconnect();
      cards.disconnect();
    };
  }, [rail, sync]);

  const scrollByPage = (direction: 1 | -1) => {
    if (!rail) return;
    rail.scrollBy({
      left: direction * rail.clientWidth * PAGE_FRACTION,
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
            ref={setRail}
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
