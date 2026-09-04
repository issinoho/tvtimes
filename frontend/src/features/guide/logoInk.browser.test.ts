import { expect, test } from 'vitest';

import { inkOf } from '@/features/guide/logoInk';

/** Needs a real browser: canvas, image decoding and getImageData. */
function load(svg: string): Promise<HTMLImageElement> {
  const img = new Image();
  img.src = `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
  return new Promise((resolve, reject) => {
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('image failed to load'));
  });
}

const box = (body: string) =>
  `<svg xmlns="http://www.w3.org/2000/svg" width="88" height="64">${body}</svg>`;

test('a white mark on transparent reads as light ink', async () => {
  const img = await load(box('<text x="44" y="40" font-size="18" fill="#ffffff">NARCOS</text>'));
  expect(inkOf(img)).toBe('light');
});

test('a charcoal mark on transparent reads as dark ink', async () => {
  // TCM and FXM ship this: near-black, but not black.
  const img = await load(box('<text x="44" y="40" font-size="18" fill="#242021">TCM</text>'));
  expect(inkOf(img)).toBe('dark');
});

test('transparent padding is ignored, not counted as dark', async () => {
  // A small mark on a big transparent canvas: averaging the alpha channel in
  // would drag every logo towards "dark" and undo the whole thing.
  const img = await load(box('<rect x="40" y="28" width="8" height="8" fill="#ffffff"/>'));
  expect(inkOf(img)).toBe('light');
});

test('a fully transparent image reports nothing rather than guessing', async () => {
  expect(inkOf(await load(box('')))).toBeNull();
});

test('an image that has not loaded reports nothing', () => {
  expect(inkOf(new Image())).toBeNull();
});
