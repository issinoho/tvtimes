import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, test } from 'vitest';

import styles from '@/features/tonight/tonight.module.css';
import '@/styles/global.css';

/**
 * The artwork wash behind a Tonight card, measured against worst-case art.
 *
 * The wash composites arbitrary imagery behind the card's own text. Whether
 * that stays legible depends on the image: a snow scene is effectively white,
 * a night shot effectively black, and an opacity that reads as a tasteful hint
 * on one is a contrast failure on the other. Picking the number by looking at
 * a few real backdrops proves nothing, because the failing image is the one
 * you didn't try.
 *
 * So this substitutes the two extremes -- a solid white image and a solid
 * black one -- and asserts the text clears AA against both, in both themes.
 * Anything real sits between them, so passing here bounds every case.
 *
 * The composite is done with canvas `globalCompositeOperation`, which
 * implements the same W3C compositing spec as CSS `mix-blend-mode`, in the
 * same engine -- rather than reimplementing the blend arithmetic here, which
 * would test my algebra instead of the browser's. Both the mode and the
 * opacity are read from the computed style, so the test tracks the CSS rather
 * than drifting from a copy of its numbers.
 *
 * The two themes are treated differently -- dark blends `color` at a high
 * opacity, light uses a plain wash at a low one -- and this reads both from
 * the computed style, so it measures whichever applies rather than assuming
 * one.
 *
 * It ignores the light-mode `filter`, and that is sound rather than an
 * oversight: `saturate()` cannot change a pure grey, and `brightness()` leaves
 * black at black and clips white at white. At exactly the two extremes
 * measured here the filter is the identity, so the bound still holds.
 *
 * To prove it bites, change the dark wash to `mix-blend-mode: normal` at its
 * opacity: it stops preserving the backdrop's luminance and the test fails.
 */

const AA = 4.5;

function rgba(colour: string): number[] {
  const canvas = document.createElement('canvas');
  canvas.width = 1;
  canvas.height = 1;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('no 2d context');
  ctx.clearRect(0, 0, 1, 1);
  ctx.fillStyle = colour;
  ctx.fillRect(0, 0, 1, 1);
  const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data;
  return [r, g, b, a / 255];
}

function channel(c: number): number {
  const v = c / 255;
  return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
}

function luminance([r, g, b]: number[]): number {
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function over(colour: string, backdrop: number[]): number[] {
  const [r, g, b, a] = rgba(colour);
  return [r, g, b].map((c, i) => a * c + (1 - a) * backdrop[i]);
}

function contrast(fg: number[], bg: number[]): number {
  const a = luminance(fg);
  const b = luminance(bg);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

/** Composite a flat art colour over the card ground exactly as the CSS does. */
function washed(card: HTMLElement, page: number[], art: number[]): number[] {
  const ground = over(getComputedStyle(card).backgroundColor, page);
  const wash = getComputedStyle(card, '::before');
  const alpha = Number(wash.opacity);
  const mode = wash.mixBlendMode;
  expect(alpha, 'the wash pseudo-element should be present').toBeGreaterThan(0);

  const canvas = document.createElement('canvas');
  canvas.width = 1;
  canvas.height = 1;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('no 2d context');
  ctx.fillStyle = `rgb(${ground.map(Math.round).join(',')})`;
  ctx.fillRect(0, 0, 1, 1);
  ctx.globalCompositeOperation = mode as GlobalCompositeOperation;
  ctx.globalAlpha = alpha;
  ctx.fillStyle = `rgb(${art.join(',')})`;
  ctx.fillRect(0, 0, 1, 1);
  const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
  return [r, g, b];
}

function renderCard(theme: 'light' | 'dark') {
  document.documentElement.setAttribute('data-theme', theme);
  return render(
    <div className={styles.rail}>
      <button type="button" className={styles.card} data-art="" data-testid="card">
        <span className={styles.now}>A Fistful of Dollars</span>
        <span className={styles.next}>Next: The Thing · 21:00</span>
      </button>
    </div>,
  );
}

afterEach(() => {
  cleanup();
  document.documentElement.removeAttribute('data-theme');
});

const EXTREMES: Array<[string, number[]]> = [
  ['white artwork', [255, 255, 255]],
  ['black artwork', [0, 0, 0]],
];

for (const theme of ['light', 'dark'] as const) {
  for (const [name, art] of EXTREMES) {
    test(`card text stays legible over ${name} in ${theme} mode`, () => {
      renderCard(theme);
      const page = over(getComputedStyle(document.body).backgroundColor, [255, 255, 255]);
      const card = screen.getByTestId('card');
      const bg = washed(card, page, art);

      const failures = [
        ['title', screen.getByText('A Fistful of Dollars')],
        ['next', screen.getByText(/^Next:/)],
      ]
        .map(([label, el]) => ({
          label,
          ratio: Number(
            contrast(over(getComputedStyle(el as HTMLElement).color, bg), bg).toFixed(2),
          ),
        }))
        .filter((r) => r.ratio < AA);

      expect(failures, `below ${AA}:1 over ${name} in ${theme} mode`).toEqual([]);
    });
  }
}

/**
 * The contrast tests above fill with a flat colour, which bounds the card's
 * *average* background but says nothing about local contrast within one card.
 * Real artwork has plenty -- a face against a sky -- and at 0.16 opacity that
 * detail lands under the title, which is how 0.1.65 shipped a wash you could
 * read a still frame through.
 *
 * The blur is what closes that gap: it collapses high-frequency detail toward
 * the average the flat fill models, so the bound above is a real one. This
 * asserts it is still there and still substantial, because removing it would
 * silently invalidate every other test in this file rather than failing one.
 */
for (const theme of ['light', 'dark'] as const) {
  test(`the wash is blurred enough for the flat-fill bound to hold in ${theme} mode`, () => {
    renderCard(theme);
    const filter = getComputedStyle(screen.getByTestId('card'), '::before').filter;
    const blur = /blur\(([\d.]+)px\)/.exec(filter);
    expect(blur, `no blur in "${filter}"`).not.toBeNull();
    expect(Number(blur?.[1]), 'blur radius').toBeGreaterThanOrEqual(12);
  });
}

test('a card with no artwork has no wash to composite', () => {
  document.documentElement.setAttribute('data-theme', 'dark');
  render(
    <button type="button" className={styles.card} data-testid="plain">
      <span className={styles.now}>Nothing TMDB matched</span>
    </button>,
  );
  // Absent data-art means the ::before never applies, so an unmatched
  // programme renders exactly as the card did before any of this.
  const cs = getComputedStyle(screen.getByTestId('plain'), '::before');
  expect(cs.content).toBe('none');
});
