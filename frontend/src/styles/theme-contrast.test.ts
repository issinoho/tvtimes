import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

import { expect, test } from 'vitest';

/**
 * Guards a whole bug class rather than one instance.
 *
 * The pills, the danger buttons and the inline error/ok messages all
 * hardcoded pale hex colours picked for the dark theme. In light mode the
 * same rule composites over white, so the text dropped to a contrast ratio
 * of about 1.2–1.6 against a 4.5 requirement — visibly blank. `--callout-*-fg`
 * already existed for exactly this and flips per theme.
 *
 * `#fff` is allowed: it is only used on the brand gradient, which stays dark
 * in both themes.
 */
function cssFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) return cssFiles(full);
    return full.endsWith('.css') && !full.endsWith('theme.css') ? [full] : [];
  });
}

test('no stylesheet hardcodes a light text colour that cannot flip with the theme', () => {
  const offenders: string[] = [];

  for (const file of cssFiles('src')) {
    readFileSync(file, 'utf8')
      .split('\n')
      .forEach((line, i) => {
        const m = /(?:^|[^-])color:\s*#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b/.exec(line);
        if (!m) return;
        const hex = m[1].length === 3 ? [...m[1]].map((c) => c + c).join('') : m[1];
        const [r, g, b] = [0, 2, 4].map((o) => parseInt(hex.slice(o, o + 2), 16));
        // White is fine (gradient buttons); anything else pale is not.
        if (hex.toLowerCase() === 'ffffff') return;
        const luma = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
        if (luma > 0.6) offenders.push(`${file}:${i + 1}  #${hex}`);
      });
  }

  expect(offenders, `use a --callout-*-fg token instead:\n${offenders.join('\n')}`).toEqual([]);
});
