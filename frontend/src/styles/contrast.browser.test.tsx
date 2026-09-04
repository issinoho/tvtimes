import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, test } from 'vitest';

import { StatusPill } from '@/features/sources/StatusPill';
import '@/styles/global.css';

/**
 * Contrast, measured rather than assumed.
 *
 * The status pills hardcoded pale colours picked for the dark theme. In light
 * mode the same rule composites over white and the text landed at about 1.2:1
 * — visibly blank. There is a static check that scans the stylesheets for
 * hardcoded pale literals, but it can only catch that one shape of mistake;
 * this measures what a viewer actually sees, whatever the CSS does to get
 * there, including through color-mix and token indirection.
 */

const AA = 4.5;
const STATUSES = ['ok', 'error', 'pending', 'stale'] as const;

/**
 * Resolve any CSS colour to [r, g, b, a] with 0-255 channels.
 *
 * Parsing the string by hand is a trap: color-mix() computes to
 * `color(srgb 0.06 0.72 0.5 / 0.22)`, whose components are 0-1, while rgb()
 * gives 0-255. Reading one as the other makes a mid-green look black and
 * reports a contrast failure that isn't real. The canvas resolves whatever
 * syntax the browser supports, in one place.
 */
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

/** Flatten a possibly-translucent colour onto an opaque backdrop. */
function over(colour: string, backdrop: number[]): number[] {
  const [r, g, b, a] = rgba(colour);
  return [r, g, b].map((c, i) => a * c + (1 - a) * backdrop[i]);
}

function contrast(fg: number[], bg: number[]): number {
  const a = luminance(fg);
  const b = luminance(bg);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

function measure(el: HTMLElement, page: number[]): number {
  const cs = getComputedStyle(el);
  const bg = over(cs.backgroundColor, page);
  return contrast(over(cs.color, bg), bg);
}

function renderPills(theme: 'light' | 'dark') {
  document.documentElement.setAttribute('data-theme', theme);
  return render(
    <div data-testid="page">
      {STATUSES.map((s) => (
        <StatusPill key={s} status={s} />
      ))}
    </div>,
  );
}

afterEach(() => {
  cleanup();
  document.documentElement.removeAttribute('data-theme');
});

for (const theme of ['light', 'dark'] as const) {
  test(`every status pill is legible in ${theme} mode`, () => {
    renderPills(theme);
    // The pill tints are translucent, so what sits behind them decides the
    // real contrast -- take it from the page rather than assuming white.
    const page = over(getComputedStyle(document.body).backgroundColor, [255, 255, 255]);

    const failures = STATUSES.map((status) => {
      const label = { ok: 'Ready', error: 'Error', pending: 'Refreshing…', stale: 'Stale' }[status];
      const ratio = measure(screen.getByText(label), page);
      return { status, ratio: Number(ratio.toFixed(2)) };
    }).filter((r) => r.ratio < AA);

    expect(failures, `below ${AA}:1 in ${theme} mode`).toEqual([]);
  });
}

/**
 * A channel logo sits on a tile of its own, because provider artwork is
 * wildly inconsistent and mostly ships on transparent: white marks (Pluto
 * and most IPTV feeds), black marks, and full-bleed colour all turn up in
 * one line-up.
 *
 * The first version of this test asserted the tile was distinguishable from
 * the *surface* — and passed while the bug was live, because that is not the
 * relationship that matters. What has to be legible is the artwork against
 * the tile, so that is what this measures: 1.5:1 for a white logo is what
 * "washed out" looked like.
 */
const ARTWORK = {
  'white (Pluto, most IPTV feeds)': [255, 255, 255],
  black: [0, 0, 0],
  'saturated yellow': [255, 233, 77],
};

// 3:1 is the WCAG bar for a graphical object, which is what a logo is.
const GRAPHIC_AA = 3;

for (const theme of ['light', 'dark'] as const) {
  test(`every kind of channel logo reads against its tile in ${theme} mode`, () => {
    document.documentElement.setAttribute('data-theme', theme);
    const surface = over(getComputedStyle(document.body).backgroundColor, [255, 255, 255]);

    const probe = document.createElement('div');
    probe.style.background = 'var(--logo-card)';
    document.body.appendChild(probe);
    // backgroundColor, not background: the shorthand computes to
    // "rgba(...) none repeat scroll ..." and splitting it on spaces yields
    // a truncated colour that silently measures as black.
    const tile = over(getComputedStyle(probe).backgroundColor, surface);
    probe.remove();

    const failures = Object.entries(ARTWORK)
      .map(([kind, mark]) => ({ kind, ratio: Number(contrast(mark, tile).toFixed(2)) }))
      .filter((r) => r.ratio < GRAPHIC_AA);

    expect(failures, `below ${GRAPHIC_AA}:1 against the logo tile in ${theme} mode`).toEqual([]);
  });
}
