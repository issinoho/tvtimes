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
 * wildly inconsistent — white-on-transparent, dark-on-transparent, full-bleed
 * colour. The tile was a translucent white tuned for the dark UI; in light
 * mode nothing dark shows through, so it resolved to near-white and every
 * white-on-transparent logo (Pluto's and most IPTV feeds') vanished.
 *
 * The tile therefore has to be distinguishable from the surface it sits on,
 * in both themes — that difference is the only thing a pale logo has to
 * read against.
 */
function distance(a: number[], b: number[]): number {
  return Math.max(...[0, 1, 2].map((i) => Math.abs(a[i] - b[i])));
}

for (const theme of ['light', 'dark'] as const) {
  test(`a channel logo tile is distinguishable from the surface in ${theme} mode`, () => {
    document.documentElement.setAttribute('data-theme', theme);
    const surface = over(getComputedStyle(document.body).backgroundColor, [255, 255, 255]);

    const probe = document.createElement('div');
    probe.style.background = 'var(--logo-card)';
    document.body.appendChild(probe);
    // backgroundColor, not background: the shorthand computes to
    // "rgba(255, 255, 255, 0.7) none repeat scroll ..." and any attempt to
    // pick the colour out of that by splitting on spaces gets "rgba(255,".
    const tile = over(getComputedStyle(probe).backgroundColor, surface);
    probe.remove();

    // A white logo against a near-white tile is the bug. 24 is comfortably
    // past "you can see the edge of it" without demanding a heavy block.
    expect(distance(tile, surface)).toBeGreaterThan(24);
  });
}
