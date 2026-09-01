import { useEffect, useRef, useState } from 'react';

import {
  usePlayLink,
  useSetChannelShift,
  type PlayLink,
  type SearchChannel,
  type Programme,
} from '@/features/guide/api';
import { GENRE_VAR, genreOf } from '@/features/guide/genre';
import { fmtDayTime } from '@/features/guide/time';
import { useHero } from '@/features/guide/hero';
import { FavStar } from '@/features/favourites/FavStar';
import { useAddWatch, useRemoveWatch, useWatchlist } from '@/features/watchlist/api';
import { ApiError } from '@/lib/api/client';
import { useAuth } from '@/lib/auth/AuthProvider';
import { isAndroid } from '@/lib/platform';
import { useDialogFocus } from '@/lib/useDialogFocus';
import styles from '@/features/guide/guide.module.css';

const SHIFT_STEPS = [-3600, -900, 0, 900, 3600] as const;
const CLAMP = 24 * 3600;

function fmtShift(seconds: number): string {
  if (seconds === 0) return 'no offset';
  const sign = seconds > 0 ? '+' : '−';
  const abs = Math.abs(seconds);
  const h = Math.floor(abs / 3600);
  const m = Math.round((abs % 3600) / 60);
  return `${sign}${h ? `${h}h` : ''}${m ? `${m}m` : ''}`;
}

function ChannelShiftControl({ channel }: { channel: SearchChannel }) {
  const [shift, setShift] = useState(channel.clock_shift_seconds);
  const mutation = useSetChannelShift();
  useEffect(() => setShift(channel.clock_shift_seconds), [channel.id, channel.clock_shift_seconds]);

  const apply = (seconds: number) => {
    const next = Math.max(-CLAMP, Math.min(CLAMP, seconds));
    setShift(next);
    mutation.mutate({ channelId: channel.id, seconds: next });
  };

  return (
    <div className={styles.shift}>
      <p className={styles.kv}>
        Listing offset for {channel.name}: <strong>{fmtShift(shift)}</strong>
      </p>
      <div className={styles.shiftBtns}>
        {SHIFT_STEPS.map((step) => (
          <button
            key={step}
            type="button"
            className={styles.btn}
            disabled={mutation.isPending}
            onClick={() => apply(step === 0 ? 0 : shift + step)}
          >
            {step === 0 ? 'Reset' : fmtShift(step)}
          </button>
        ))}
      </div>
      <p className={styles.kvDim}>
        Added to every programme time on this channel — e.g. +3h to match a US-West feed to an
        East-coast guide. The grid updates as you adjust.
      </p>
    </div>
  );
}

interface Props {
  channel: SearchChannel;
  programme: Programme;
  onClose: () => void;
}

function WatchControls({ channel, programme }: { channel: SearchChannel; programme: Programme }) {
  const { user } = useAuth();
  const { data } = useWatchlist();
  const add = useAddWatch();
  const remove = useRemoveWatch();
  const items = data?.items ?? [];

  const startMs = new Date(programme.start).getTime();
  const airing = items.find(
    (i) =>
      i.kind === 'programme' &&
      i.channel_id === channel.id &&
      i.start != null &&
      Math.abs(new Date(i.start).getTime() - startMs) < 60_000,
  );
  const title = items.find(
    (i) => i.kind === 'title' && i.title.toLowerCase() === programme.title.toLowerCase(),
  );
  const busy = add.isPending || remove.isPending;

  return (
    <div>
      <div className={styles.watchRow}>
        <button
          type="button"
          className={styles.btn}
          data-on={airing ? 'true' : undefined}
          disabled={busy}
          onClick={() =>
            airing
              ? remove.mutate(airing.id)
              : add.mutate({ kind: 'programme', programme_id: programme.id })
          }
        >
          {airing ? '✓ Reminder set' : 'Remind me'}
        </button>
        <button
          type="button"
          className={styles.btn}
          data-on={title ? 'true' : undefined}
          disabled={busy}
          onClick={() =>
            title ? remove.mutate(title.id) : add.mutate({ kind: 'title', title: programme.title })
          }
        >
          {title ? '✓ Watching this title' : 'Watch this title'}
        </button>
      </div>
      {user && !user.email_verified ? (
        <p className={styles.watchHint}>Verify your email to receive reminders.</p>
      ) : (
        <p className={styles.watchHint}>Reminders arrive by email ~15 min before air time.</p>
      )}
    </div>
  );
}

function androidIntentUrl(link: PlayLink, title: string): string {
  const u = new URL(link.stream_url);
  const scheme = u.protocol.replace(':', '');
  return (
    `intent://${u.host}${u.pathname}${u.search}` +
    `#Intent;scheme=${scheme};action=android.intent.action.VIEW;type=video/*;` +
    `S.title=${encodeURIComponent(title)};` +
    `S.browser_fallback_url=${encodeURIComponent(link.m3u_url)};end`
  );
}

export function PlayControls({ channel }: { channel: SearchChannel }) {
  const mint = usePlayLink();
  const cached = useRef<{ id: string; link: PlayLink } | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function getLink(): Promise<PlayLink> {
    if (cached.current?.id === channel.id) return cached.current.link;
    const link = await mint.mutateAsync(channel.id);
    cached.current = { id: channel.id, link };
    return link;
  }

  function fail(err: unknown) {
    setError(
      err instanceof ApiError && err.status === 501
        ? 'Not available for this source.'
        : "Couldn't start playback.",
    );
  }

  const android = isAndroid();

  async function play() {
    setError(null);
    try {
      const link = await getLink();
      // Desktop: hand the OS a `tvdinner:` link so it opens straight in
      // tvdinner (one remembered browser prompt, nothing saved). Android:
      // the intent chooser, as before.
      window.location.assign(
        android ? androidIntentUrl(link, channel.name) : `tvdinner:${link.m3u_url}`,
      );
    } catch (err) {
      fail(err);
    }
  }

  async function download() {
    setError(null);
    try {
      const link = await getLink();
      window.location.assign(link.m3u_url); // plain .m3u download, for any other player
    } catch (err) {
      fail(err);
    }
  }

  async function copy() {
    setError(null);
    try {
      const link = await getLink();
      await navigator.clipboard.writeText(link.stream_url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch (err) {
      if (err instanceof ApiError) fail(err);
    }
  }

  return (
    <div>
      <div className={styles.watchRow}>
        <button type="button" className={styles.btn} disabled={mint.isPending} onClick={play}>
          {mint.isPending ? 'Starting…' : 'Play'}
        </button>
        <button type="button" className={styles.btn} disabled={mint.isPending} onClick={download}>
          Download .m3u
        </button>
        <button type="button" className={styles.btn} disabled={mint.isPending} onClick={copy}>
          {copied ? 'Copied' : 'Copy stream URL'}
        </button>
      </div>
      {error ? (
        <p className={styles.watchHint}>{error}</p>
      ) : (
        <p className={styles.watchHint}>
          {android
            ? 'Opens in your device’s default media player.'
            : 'Play hands off to tvdinner; Download .m3u opens in any player.'}
        </p>
      )}
    </div>
  );
}

export function ProgrammeSheet({ channel, programme, onClose }: Props) {
  const { data: hero } = useHero(programme.id);
  const sheetRef = useDialogFocus<HTMLElement>();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const start = new Date(programme.start);
  const stop = new Date(programme.stop);
  const now = Date.now();
  const live = now >= start.getTime() && now < stop.getTime();
  const pct = live
    ? Math.round(((now - start.getTime()) / (stop.getTime() - start.getTime())) * 100)
    : 0;
  const fmt = (d: Date) => fmtDayTime(d, channel.timezone);

  const e = hero?.enrichment ?? null;
  const genre = genreOf(programme.categories, programme.is_movie);
  const description = e?.overview ?? programme.description;
  const genreList = e?.genres.length ? e.genres : programme.categories;
  const year = e?.release_year ?? programme.year;

  return (
    <>
      <div className={styles.sheetBackdrop} onClick={onClose} />
      <aside
        ref={sheetRef}
        className={styles.sheet}
        style={{ ['--genre' as string]: GENRE_VAR[genre] }}
        role="dialog"
        aria-modal="true"
        aria-label={programme.title}
        tabIndex={-1}
      >
        <button type="button" className={`${styles.btn} ${styles.close}`} onClick={onClose}>
          Close
        </button>

        {e?.backdrop_url ? (
          <div
            className={styles.heroArt}
            style={{ backgroundImage: `url(${e.backdrop_url})` }}
            aria-hidden
          >
            {e.logo_url ? <img className={styles.heroLogo} src={e.logo_url} alt="" /> : null}
          </div>
        ) : null}

        <p className={styles.kv}>
          {channel.name}
          <FavStar channelId={channel.id} />
        </p>
        <h2>{programme.title}</h2>
        {programme.sub_title ? <p className={styles.kv}>{programme.sub_title}</p> : null}
        {e?.tagline ? <p className={styles.tagline}>{e.tagline}</p> : null}

        <p className={styles.when}>
          {fmt(start)} – {fmt(stop)}
          {year ? ` · ${year}` : ''}
          {e?.runtime ? ` · ${e.runtime} min` : ''}
          {live ? ' · on now' : ''}
        </p>
        {live ? (
          <div className={styles.progress}>
            <span style={{ width: `${pct}%` }} />
          </div>
        ) : null}

        <WatchControls channel={channel} programme={programme} />
        <PlayControls channel={channel} />

        {e?.rating != null ? (
          <p className={styles.rating}>
            ★ {e.rating.toFixed(1)}
            <span className={styles.attribution}> · TMDB</span>
          </p>
        ) : null}

        {genreList.length ? (
          <div className={styles.chipRow}>
            {genreList.map((c) => (
              <span key={c} className={styles.gchip}>
                {c}
              </span>
            ))}
          </div>
        ) : null}

        {programme.episode_num ? (
          <p className={styles.kv}>Episode {programme.episode_num}</p>
        ) : null}
        {e?.director ? <p className={styles.kv}>Directed by {e.director}</p> : null}
        {e?.cast.length ? (
          <p className={styles.kv}>
            {e.cast
              .slice(0, 6)
              .map((c) => c.name)
              .join(', ')}
          </p>
        ) : null}

        {description ? (
          <p className={styles.desc}>{description}</p>
        ) : (
          <p className={styles.kv}>No description in this guide.</p>
        )}

        <ChannelShiftControl channel={channel} />

        {hero?.enriching ? (
          <p className={styles.kv} style={{ marginTop: '1rem' }}>
            Fetching artwork and details from TMDB…
          </p>
        ) : null}
        {hero && !hero.tmdb_connected ? (
          <p className={styles.kv} style={{ marginTop: '1rem' }}>
            Add a TMDB key in Settings for backdrops, cast and ratings.
          </p>
        ) : null}
      </aside>
    </>
  );
}
