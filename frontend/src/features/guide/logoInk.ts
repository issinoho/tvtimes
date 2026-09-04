/**
 * Whether a channel logo is drawn in light ink or dark ink.
 *
 * Provider artwork is mostly transparent PNGs, and a single line-up will
 * contain pure-white marks (Pluto, Narcos), near-black ones (TCM, FXM) and
 * full-bleed colour. No one tile colour serves them: measured across the
 * marks in a real line-up, the best possible flat background scores 3.23:1
 * in its worst case, which clears the 3:1 bar for a graphical element with
 * no headroom at all — one new channel with a mid-grey logo breaks it.
 *
 * So the ground adapts to the artwork instead. Logos are always fetched
 * through our own origin proxy, so the canvas isn't tainted and the pixels
 * can be read.
 */

function toLinear(c: number): number {
  const v = c / 255;
  return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
}

/** Sampled small: enough to judge the ink, cheap enough to run per logo. */
const SAMPLE = 24;

/** Above this mean luminance the mark counts as light ink. */
const LIGHT_INK = 0.45;

/** Ignore near-transparent pixels — the padding says nothing about the ink. */
const MIN_ALPHA = 0.1;

export type Ink = 'light' | 'dark';

/**
 * `null` when the logo is blank, still loading, or the read fails — the
 * caller keeps the neutral default rather than guessing.
 */
export function inkOf(image: HTMLImageElement): Ink | null {
  if (!image.naturalWidth || !image.naturalHeight) return null;
  try {
    const canvas = document.createElement('canvas');
    canvas.width = SAMPLE;
    canvas.height = SAMPLE;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) return null;
    ctx.drawImage(image, 0, 0, SAMPLE, SAMPLE);
    const { data } = ctx.getImageData(0, 0, SAMPLE, SAMPLE);

    let weighted = 0;
    let weight = 0;
    for (let i = 0; i < data.length; i += 4) {
      const alpha = data[i + 3] / 255;
      if (alpha < MIN_ALPHA) continue;
      const luminance =
        0.2126 * toLinear(data[i]) +
        0.7152 * toLinear(data[i + 1]) +
        0.0722 * toLinear(data[i + 2]);
      weighted += alpha * luminance;
      weight += alpha;
    }
    if (weight === 0) return null;
    return weighted / weight > LIGHT_INK ? 'light' : 'dark';
  } catch {
    // A tainted canvas would throw here. Shouldn't happen via the proxy, but
    // a neutral tile is a better outcome than a broken logo column.
    return null;
  }
}
