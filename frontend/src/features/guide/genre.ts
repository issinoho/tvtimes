/** Map an XMLTV category to one of the fixed genre buckets from docs/brand.md. */

export type Genre =
  'film' | 'sport' | 'news' | 'kids' | 'doc' | 'ent' | 'drama' | 'music' | 'default';

const RULES: [Genre, RegExp][] = [
  ['film', /\b(movie|film|cinema)\b/i],
  ['sport', /\b(sport|football|soccer|tennis|golf|racing|rugby|cricket|boxing)\b/i],
  ['news', /\b(news|current affairs|weather|politic)\b/i],
  ['kids', /\b(kids?|children|cartoon|animation|family)\b/i],
  ['doc', /\b(documentar|nature|history|science|factual)\b/i],
  ['music', /\b(music|concert|gig)\b/i],
  ['drama', /\b(drama|series|soap|crime|thriller|mystery)\b/i],
  ['ent', /\b(entertainment|comedy|reality|talk|game show|quiz|chat)\b/i],
];

export function genreOf(categories: string[], isMovie: boolean): Genre {
  if (isMovie) return 'film';
  const hay = categories.join(' ');
  for (const [genre, re] of RULES) if (re.test(hay)) return genre;
  return 'default';
}

export const GENRE_VAR: Record<Genre, string> = {
  film: 'var(--genre-film)',
  sport: 'var(--genre-sport)',
  news: 'var(--genre-news)',
  kids: 'var(--genre-kids)',
  doc: 'var(--genre-doc)',
  ent: 'var(--genre-ent)',
  drama: 'var(--genre-drama)',
  music: 'var(--genre-music)',
  default: 'var(--genre-default)',
};
