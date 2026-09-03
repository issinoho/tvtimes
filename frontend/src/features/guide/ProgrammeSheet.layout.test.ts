import { readFileSync } from 'node:fs';

import { expect, test } from 'vitest';

// jsdom does no layout, so these assert the rules rather than the rendering.
// That is exactly the gap that let the bug below ship unnoticed.
const css = readFileSync('src/features/guide/guide.module.css', 'utf8');

function block(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`${escaped}\\s*\\{([^}]*)\\}`).exec(css)?.[1] ?? '';
}

test('the sheet close button sits above the hero artwork', () => {
  // .heroArt is positioned, comes after the button in the DOM, and its
  // negative margins pull it into the button's corner. With both at
  // z-index auto the artwork won -- it hid the button *and* took its
  // clicks, leaving no visible way to close the sheet.
  const close = block('.sheet .close');
  expect(close).toMatch(/position:\s*absolute/);
  expect(close).toMatch(/z-index:\s*[1-9]/);
});

test('the hero artwork does not raise itself above the sheet chrome', () => {
  // The other half of the same invariant: giving .heroArt a z-index would
  // put it back on top however high the button goes.
  expect(block('.heroArt')).not.toMatch(/z-index:/);
});

test('the sheet shell does not scroll, so the Close button stays put', () => {
  // The button is absolutely positioned against .sheet. If .sheet is itself
  // the scroll container the button scrolls away with the content -- on a long
  // description its top went from 34px to -566px, off the viewport entirely.
  // The scrolling moved to .sheetBody so the shell stays still.
  const sheet = block('.sheet');
  expect(sheet).not.toMatch(/overflow-y:\s*(auto|scroll)/);
  expect(sheet).toMatch(/overflow:\s*hidden/);

  const body = block('.sheetBody');
  expect(body).toMatch(/overflow-y:\s*auto/);
  // Flex child rather than height:100%: on mobile the sheet is a bottom sheet
  // whose height is content-driven, where a percentage wouldn't resolve.
  expect(body).toMatch(/min-height:\s*0/);
});
