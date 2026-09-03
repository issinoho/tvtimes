import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { useProgrammeSearch, type SearchChannel, type Programme } from '@/features/guide/api';
import { ChannelLogo } from '@/features/guide/ChannelLogo';
import { ProgrammeSheet } from '@/features/guide/ProgrammeSheet';
import { fmtDayTime } from '@/features/guide/time';
import styles from '@/features/search/search.module.css';

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return debounced;
}

export function SearchPage() {
  // `?q=` seeds the box, so anything can hand a title over — tvdinner's "look
  // this up in tvtimes" keybinding does. Read once, as the initial value:
  // making it controlled would fight the user's own typing on every keystroke.
  const [params, setParams] = useSearchParams();
  const [text, setText] = useState(() => params.get('q') ?? '');
  const [moviesOnly, setMoviesOnly] = useState(false);
  const [open, setOpen] = useState<{ channel: SearchChannel; programme: Programme } | null>(null);

  // Drop it from the URL once consumed, so a reload or a back-nav doesn't
  // resurrect a search the user has since typed past.
  useEffect(() => {
    if (!params.has('q')) return;
    const next = new URLSearchParams(params);
    next.delete('q');
    setParams(next, { replace: true });
  }, [params, setParams]);

  const query = useDebounced(text.trim(), 250);
  const { data, isFetching, isError } = useProgrammeSearch(query, moviesOnly);
  const results = useMemo(() => data?.results ?? [], [data]);
  const short = query.length > 0 && query.length < 2;

  return (
    <div className={styles.page}>
      <h1 className={styles.title}>Search the guide</h1>

      <div className={styles.controls}>
        <input
          className={styles.input}
          type="search"
          autoFocus
          placeholder="Film or programme title…"
          value={text}
          onChange={(e) => setText(e.target.value)}
        />
        <label className={styles.toggle}>
          <input
            type="checkbox"
            checked={moviesOnly}
            onChange={(e) => setMoviesOnly(e.target.checked)}
          />
          Films only
        </label>
      </div>

      {short ? (
        <p className={styles.hint}>Type at least two characters.</p>
      ) : isError ? (
        <p className={styles.hint}>Something went wrong. Try again.</p>
      ) : query.length < 2 ? (
        <p className={styles.hint}>Search titles across every channel for the next two weeks.</p>
      ) : results.length === 0 && !isFetching ? (
        <p className={styles.hint}>Nothing matching “{query}” in the next two weeks.</p>
      ) : (
        <ul className={styles.results}>
          {results.map((hit) => (
            <li key={`${hit.channel.id}:${hit.programme.id}`}>
              <button
                type="button"
                className={styles.row}
                onClick={() => setOpen({ channel: hit.channel, programme: hit.programme })}
              >
                <ChannelLogo
                  channelId={hit.channel.id}
                  hasLogo={Boolean(hit.channel.logo_url)}
                  imgClassName={styles.logo}
                  emptyClassName={styles.logoEmpty}
                />
                <span className={styles.main}>
                  <span className={styles.name}>
                    {hit.programme.title}
                    {hit.programme.year ? ` · ${hit.programme.year}` : ''}
                  </span>
                  <span className={styles.meta}>
                    {hit.channel.name} · {fmtDayTime(hit.programme.start, hit.channel.timezone)}
                  </span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {open ? (
        <ProgrammeSheet
          channel={open.channel}
          programme={open.programme}
          onClose={() => setOpen(null)}
        />
      ) : null}
    </div>
  );
}
