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
 * A channel logo's tile adapts to its artwork, because no flat colour can
 * serve a line-up containing pure-white marks (Pluto, Narcos), near-black
 * ones (TCM, FXM) and colour. Two attempts proved that the hard way: a light
 * tile left white logos at 1.50:1, a dark one left charcoal at 2.85:1, and
 * the mathematically optimal flat value tops out at 3.23:1 with no headroom.
 *
 * The inks below were sampled from real screenshots rather than invented.
 * That distinction matters: an earlier version of this measured pure black,
 * which no real logo uses, and the tile it blessed failed on the charcoal
 * that TCM and FXM actually ship.
 */
const LIGHT_INK = {
  white: [255, 255, 255],
  'off-white (80s Rewind)': [240, 229, 228],
  'grey-white (90s Throwback)': [218, 208, 211],
  'pluto yellow': [255, 233, 77],
};
const DARK_INK = {
  'charcoal (TCM, FXM)': [36, 32, 33],
  black: [0, 0, 0],
};

// 3:1 is the WCAG bar for a graphical object, which is what a logo is.
const GRAPHIC_AA = 3;

function tokenColour(token: string, surface: number[]): number[] {
  const probe = document.createElement('div');
  probe.style.background = `var(${token})`;
  document.body.appendChild(probe);
  // backgroundColor, not background: the shorthand computes to
  // "rgba(...) none repeat scroll ..." and splitting it on spaces yields a
  // truncated colour that silently measures as black.
  const resolved = over(getComputedStyle(probe).backgroundColor, surface);
  probe.remove();
  return resolved;
}

for (const theme of ['light', 'dark'] as const) {
  test(`each logo ground suits the ink it is for, in ${theme} mode`, () => {
    document.documentElement.setAttribute('data-theme', theme);
    const surface = over(getComputedStyle(document.body).backgroundColor, [255, 255, 255]);

    const cases: [string, Record<string, number[]>][] = [
      ['--logo-card-on-light-ink', LIGHT_INK],
      ['--logo-card-on-dark-ink', DARK_INK],
      // The neutral has to carry every ink: it is what shows while the
      // artwork is still being read, and if reading it ever fails.
      ['--logo-card', { ...LIGHT_INK, ...DARK_INK }],
    ];

    const failures = cases.flatMap(([token, inks]) => {
      const ground = tokenColour(token, surface);
      return Object.entries(inks)
        .map(([kind, ink]) => ({ token, kind, ratio: Number(contrast(ink, ground).toFixed(2)) }))
        .filter((r) => r.ratio < GRAPHIC_AA);
    });

    expect(failures, `below ${GRAPHIC_AA}:1 against their logo ground in ${theme} mode`).toEqual(
      [],
    );
  });
}
