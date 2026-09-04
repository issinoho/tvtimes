import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';

import { expect, test } from 'vitest';

/**
 * Every channel logo must load through `/api/channels/{id}/logo`.
 *
 * Provider logo_url values are routinely `http://` on a LAN — an HDHomeRun at
 * http://192.168.0.11, a Pluto feed at http://192.168.0.218 — and an https
 * page blocks those as mixed content, so the image silently fails and leaves
 * an empty tile. The source's channel table rendered `logo_url` directly and
 * showed blanks for channels whose logos were fine in the guide, which goes
 * through the proxy.
 */
/** Identifiers holding a TMDB enrichment, not a channel. */
const TMDB_ENRICHMENT = new Set(['e', 'enrichment', 'hero']);

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) return sourceFiles(full);
    return /\.tsx$/.test(full) && !/\.test\.tsx$/.test(full) ? [full] : [];
  });
}

test('no component renders a channel logo straight from its provider URL', () => {
  const offenders: string[] = [];

  for (const file of sourceFiles('src')) {
    readFileSync(file, 'utf8')
      .split('\n')
      .forEach((line, i) => {
        const direct = /src=\{\s*([A-Za-z_$][\w$]*)\??\.logo_url/.exec(line);
        if (!direct) return;
        // TMDB enrichment artwork is the one legitimate exception: it is a
        // film's title treatment, not a channel logo, and image.tmdb.org
        // serves it over https already.
        if (TMDB_ENRICHMENT.has(direct[1])) return;
        offenders.push(`${file}:${i + 1}`);
      });
  }

  expect(offenders, `use <ChannelLogo> instead:\n${offenders.join('\n')}`).toEqual([]);
});
