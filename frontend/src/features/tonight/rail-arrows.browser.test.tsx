import { cleanup, render, screen } from '@testing-library/react';
import { useEffect, useState } from 'react';
import { afterEach, expect, test } from 'vitest';

import { RailSection } from '@/features/tonight/RailSection';
import styles from '@/features/tonight/tonight.module.css';
import '@/styles/global.css';

/**
 * The arrows exist so a Fire TV remote can move a rail it cannot otherwise
 * reach (see RailSection.tsx). Whether a press actually moves it is a
 * question about scroll position and the box model, neither of which jsdom
 * has — the jsdom suite can only check that scrollBy was asked. This checks
 * the rail arrived somewhere.
 */

function cards(count: number) {
  return Array.from({ length: count }, (_, i) => (
    <button key={i} type="button" className={styles.card}>
      <span className={styles.now}>Film {i}</span>
    </button>
  ));
}

function Rail({ count = 24 }: { count?: number }) {
  return (
    <div style={{ width: '600px' }}>
      <RailSection heading="Films on soon">{cards(count)}</RailSection>
    </div>
  );
}

/**
 * The shape TonightPage actually renders: the section is on screen straight
 * away and the cards land when the query resolves, so the rail element itself
 * mounts a beat after its section.
 */
function LateRail({ count = 24 }: { count?: number }) {
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    const id = setTimeout(() => setLoaded(true), 10);
    return () => clearTimeout(id);
  }, []);
  return (
    <div style={{ width: '600px' }}>
      <RailSection heading="Films on soon">{loaded ? cards(count) : null}</RailSection>
    </div>
  );
}

const back = () => screen.getByRole('button', { name: 'Scroll back through Films on soon' });
const forward = () => screen.getByRole('button', { name: 'Scroll forward through Films on soon' });
const rail = () => screen.getByRole('group', { name: 'Films on soon' });

/** The arrows appear on the first ResizeObserver callback, not on first paint. */
async function arrowsReady() {
  await expect.poll(() => screen.queryAllByRole('button', { name: /^Scroll/ })).toHaveLength(2);
}

afterEach(cleanup);

test('a press moves the rail, and the far end dims once there is nothing left to reach', async () => {
  render(<Rail />);
  await arrowsReady();
  const el = rail();

  expect(el.scrollWidth).toBeGreaterThan(el.clientWidth); // the premise
  expect(back()).toHaveAttribute('aria-disabled', 'true');
  expect(forward()).toHaveAttribute('aria-disabled', 'false');
  // Dimmed, but never `disabled` -- that would drop focus and strand a d-pad
  // walk at the end of the rail.
  expect((back() as HTMLButtonElement).disabled).toBe(false);
  back().focus();
  expect(document.activeElement).toBe(back());

  forward().click();
  await expect.poll(() => el.scrollLeft).toBeGreaterThan(0);
  // Nearly a screenful, not the whole row.
  expect(el.scrollLeft).toBeLessThan(el.clientWidth);
  await expect.poll(() => back().getAttribute('aria-disabled')).toBe('false');

  back().click();
  await expect.poll(() => el.scrollLeft).toBe(0);
  await expect.poll(() => back().getAttribute('aria-disabled')).toBe('true');
});

/** Wait for a smooth scroll to finish: pressing again mid-flight loses the
 *  remainder of the one still animating. */
async function settled(el: HTMLElement) {
  let previous = -1;
  await expect
    .poll(() => {
      const here = el.scrollLeft;
      const stopped = here === previous;
      previous = here;
      return stopped;
    })
    .toBe(true);
}

test('walking forward reaches the end of the rail and stops there', async () => {
  render(<Rail />);
  await arrowsReady();
  const el = rail();

  for (let i = 0; i < 20 && forward().getAttribute('aria-disabled') === 'false'; i++) {
    forward().click();
    await settled(el);
  }

  await expect.poll(() => forward().getAttribute('aria-disabled')).toBe('true');
  expect(el.scrollLeft).toBeGreaterThan(el.scrollWidth - el.clientWidth - 2);
});

test('a rail short enough to fit shows no arrows at all', async () => {
  render(<Rail count={2} />);

  const el = rail();
  expect(el.scrollWidth).toBeLessThanOrEqual(el.clientWidth + 1);
  await expect.poll(() => screen.queryByRole('button', { name: /^Scroll/ })).toBe(null);
});

test('a rail whose cards arrive after it mounts still tracks where it is', async () => {
  // The regression: the rail element is not in the first render, so a plain
  // ref never re-ran the effect that listens for its scrolls. The arrows
  // appeared, the rail moved, and the back arrow stayed dimmed for good.
  render(<LateRail />);

  await arrowsReady();
  const el = rail();
  expect(back()).toHaveAttribute('aria-disabled', 'true');

  forward().click();
  await expect.poll(() => el.scrollLeft).toBeGreaterThan(0);
  await expect.poll(() => back().getAttribute('aria-disabled')).toBe('false');
});
