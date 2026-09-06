import { cleanup, render, screen } from '@testing-library/react';
import { page } from '@vitest/browser/context';
import { afterEach, expect, test } from 'vitest';

import styles from '@/features/tonight/tonight.module.css';
import '@/styles/global.css';

/**
 * The card shows the programme's artwork as a picture, with the title on top
 * of it. Whether that stays readable is decided by pixels, so this measures
 * pixels.
 *
 * An earlier version of this test composited a flat white and a flat black
 * through the CSS blend mode and checked the result. The arithmetic was right
 * and the conclusion was wrong: a flat fill bounds the card's *average*
 * background, and real artwork has local structure -- a dark face against a
 * bright sky inside one 220px card puts high contrast directly under the
 * title, which no average can see. A version shipped that way and was legible
 * only by luck.
 *
 * So: render over deliberately hostile artwork, screenshot what the browser
 * actually composited, and find the *worst* pixel behind each run of text.
 * The text is hidden for the shot -- visibility, so layout is untouched --
 * because otherwise the glyphs themselves would be sampled as background.
 */

const AA = 4.5;

/**
 * Artwork chosen to break things rather than to look nice: a bright sky over a
 * hard-edged dark ground, a dark head against the bright half, and fine noise.
 * Every one of those is a case a blurred or averaged test would wave through.
 */
function hostileArtwork(): string {
  const c = document.createElement('canvas');
  c.width = 640;
  c.height = 360;
  const ctx = c.getContext('2d');
  if (!ctx) throw new Error('no 2d context');
  const sky = ctx.createLinearGradient(0, 0, 0, 180);
  sky.addColorStop(0, '#ffffff');
  sky.addColorStop(1, '#d8e6f6');
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, 640, 180);
  ctx.fillStyle = '#101018';
  ctx.fillRect(0, 180, 640, 180);
  ctx.beginPath();
  ctx.arc(240, 150, 95, 0, Math.PI * 2);
  ctx.fill();
  for (let i = 0; i < 400; i++) {
    ctx.fillStyle = i % 2 ? '#ffffff' : '#000000';
    ctx.fillRect(Math.random() * 640, Math.random() * 360, 4, 4);
  }
  return c.toDataURL('image/png');
}

function channel(v: number): number {
  const x = v / 255;
  return x <= 0.04045 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4;
}

function luminance(r: number, g: number, b: number): number {
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function contrast(a: number, b: number): number {
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}

function rgb(colour: string): [number, number, number] {
  const c = document.createElement('canvas');
  c.width = 1;
  c.height = 1;
  const ctx = c.getContext('2d');
  if (!ctx) throw new Error('no 2d context');
  ctx.fillStyle = colour;
  ctx.fillRect(0, 0, 1, 1);
  const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
  return [r, g, b];
}

async function decode(base64: string): Promise<ImageData> {
  const img = new Image();
  img.src = base64.startsWith('data:') ? base64 : `data:image/png;base64,${base64}`;
  await img.decode();
  const c = document.createElement('canvas');
  c.width = img.naturalWidth;
  c.height = img.naturalHeight;
  const ctx = c.getContext('2d');
  if (!ctx) throw new Error('no 2d context');
  ctx.drawImage(img, 0, 0);
  return ctx.getImageData(0, 0, c.width, c.height);
}

function renderCard(theme: 'light' | 'dark') {
  document.documentElement.setAttribute('data-theme', theme);
  return render(
    <div className={styles.rail}>
      <button
        type="button"
        className={styles.card}
        data-art=""
        data-testid="card"
        style={{ ['--art' as string]: `url(${hostileArtwork()})` }}
      >
        <div className={styles.cardHead}>
          <span className={styles.channel}>TCM</span>
        </div>
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

for (const theme of ['light', 'dark'] as const) {
  test(`every run of card text clears AA over hostile artwork in ${theme} mode`, async () => {
    renderCard(theme);
    const card = screen.getByTestId('card');
    const runs = [
      ['title', screen.getByText('A Fistful of Dollars')],
      ['next', screen.getByText(/^Next:/)],
      ['channel', screen.getByText('TCM')],
    ] as const;

    // Colour and position while the text is visible, then hide it so the shot
    // captures only what sits behind it. visibility keeps the layout.
    const probes = runs.map(([label, el]) => {
      const style = getComputedStyle(el);
      const box = el.getBoundingClientRect();
      const cardBox = card.getBoundingClientRect();
      return {
        label,
        ink: luminance(...rgb(style.color)),
        rect: {
          x: box.left - cardBox.left,
          y: box.top - cardBox.top,
          w: box.width,
          h: box.height,
        },
      };
    });
    runs.forEach(([, el]) => (el.style.visibility = 'hidden'));

    // save: false makes this resolve to the base64 string itself rather than a
    // path -- nothing is written to disk.
    const shot = await page.screenshot({ element: card, save: false });
    const data = await decode(shot);
    const scale = data.width / card.getBoundingClientRect().width;

    const failures = probes
      .map(({ label, ink, rect }) => {
        let worst = Infinity;
        const x0 = Math.max(0, Math.round(rect.x * scale));
        const x1 = Math.min(data.width, Math.round((rect.x + rect.w) * scale));
        const y0 = Math.max(0, Math.round(rect.y * scale));
        const y1 = Math.min(data.height, Math.round((rect.y + rect.h) * scale));
        for (let y = y0; y < y1; y++) {
          for (let x = x0; x < x1; x++) {
            const i = (y * data.width + x) * 4;
            const lum = luminance(data.data[i], data.data[i + 1], data.data[i + 2]);
            worst = Math.min(worst, contrast(ink, lum));
          }
        }
        return { label, worst: Number(worst.toFixed(2)) };
      })
      .filter((r) => r.worst < AA);

    expect(failures, `worst pixel behind the text is below ${AA}:1 in ${theme} mode`).toEqual([]);
  });
}

test('a card with no artwork draws neither the still nor its scrim', () => {
  document.documentElement.setAttribute('data-theme', 'dark');
  render(
    <button type="button" className={styles.card} data-testid="plain">
      <span className={styles.now}>Nothing TMDB matched</span>
    </button>,
  );
  const plain = screen.getByTestId('plain');
  expect(getComputedStyle(plain, '::before').content).toBe('none');
  expect(getComputedStyle(plain, '::after').content).toBe('none');
});
