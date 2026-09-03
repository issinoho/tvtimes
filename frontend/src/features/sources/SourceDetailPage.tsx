import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { EpgPanel } from '@/features/sources/EpgPanel';
import { StatusPill } from '@/features/sources/StatusPill';
import {
  useChannels,
  useDeleteSource,
  usePatchSource,
  useRefreshSource,
  useSetChannelEpgOverride,
  useSource,
} from '@/features/sources/api';
import styles from '@/features/sources/sources.module.css';
import type { components } from '@/lib/api/schema';

type Channel = components['schemas']['ChannelOut'];

const PAGE = 50;

/**
 * The guide key a channel is matched on, editable in place.
 *
 * Only earns its keep for a channel showing 0 programmes: it means the
 * channel's own tvg-id and names found nothing in the guide, and this is the
 * only way to say what to look for instead.
 */
function GuideKeyCell({ channel, sourceId }: { channel: Channel; sourceId: string }) {
  const [value, setValue] = useState(channel.epg_override_id ?? '');
  const mutation = useSetChannelEpgOverride(sourceId);
  const saved = channel.epg_override_id ?? '';

  return (
    <form
      className={styles.guideKey}
      onSubmit={(e) => {
        e.preventDefault();
        if (value.trim() !== saved) mutation.mutate({ channelId: channel.id, value });
      }}
    >
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={() => {
          if (value.trim() !== saved) mutation.mutate({ channelId: channel.id, value });
        }}
        placeholder={channel.ext_id ?? '—'}
        aria-label={`Guide key for ${channel.name}`}
        disabled={mutation.isPending}
      />
    </form>
  );
}

export function SourceDetailPage() {
  const { sourceId = '' } = useParams();
  const navigate = useNavigate();
  const { data: source, isPending } = useSource(sourceId);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const channels = useChannels(sourceId, {
    search: search || undefined,
    limit: PAGE,
    offset: page * PAGE,
  });

  const refresh = useRefreshSource();
  const remove = useDeleteSource();
  const patch = usePatchSource(sourceId);

  if (isPending) return <p>Loading…</p>;
  if (!source) return <p>Source not found.</p>;

  const total = channels.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PAGE));

  return (
    <div className={styles.page}>
      <div className={styles.detailHead}>
        <div>
          <h1 style={{ margin: 0 }}>
            <span className={styles.kindTag}>{source.kind}</span>
            {source.display_name}
          </h1>
          <p className={styles.sub} style={{ marginTop: '0.35rem' }}>
            {source.config_summary}
          </p>
        </div>
        <StatusPill status={source.health} />
      </div>

      {source.last_status === 'error' && source.last_error ? (
        <p className={styles.err}>{source.last_error}</p>
      ) : null}
      {source.health === 'stale' && source.last_status !== 'error' ? (
        <p className={styles.sub}>
          Hasn’t refreshed recently — check the worker is running, then try “Refresh now”.
        </p>
      ) : null}

      <EpgPanel sourceId={sourceId} />

      <div className={styles.toolbar}>
        <button
          type="button"
          className={styles.btn}
          onClick={() => refresh.mutate(sourceId)}
          disabled={refresh.isPending || source.last_status === 'pending'}
        >
          {source.last_status === 'pending' ? 'Refreshing…' : 'Refresh now'}
        </button>
        <button
          type="button"
          className={styles.btn}
          onClick={() => patch.mutate({ enabled: !source.enabled })}
        >
          {source.enabled ? 'Disable' : 'Enable'}
        </button>
        <button
          type="button"
          className={`${styles.btn} ${styles.danger}`}
          onClick={async () => {
            if (!window.confirm('Remove this source and its channels?')) return;
            await remove.mutateAsync(sourceId);
            await navigate('/sources', { replace: true });
          }}
        >
          Delete
        </button>
      </div>

      <div className={styles.toolbar}>
        <input
          className={styles.search}
          aria-label="Filter channels"
          placeholder="Filter channels…"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(0);
          }}
        />
        <span className={styles.sub}>{total} channels</span>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table className={styles.channels}>
          <thead>
            <tr>
              <th />
              <th>Name</th>
              <th>Group</th>
              <th>No.</th>
              <th>Guide</th>
              <th>Guide key</th>
            </tr>
          </thead>
          <tbody>
            {(channels.data?.items ?? []).map((c) => (
              <tr key={c.id}>
                <td>
                  {c.logo_url ? <img className={styles.logo} src={c.logo_url} alt="" /> : null}
                </td>
                <td>
                  {c.name}
                  {c.is_hd ? <span className={styles.kindTag}> HD</span> : null}
                </td>
                <td>{c.group_title ?? '—'}</td>
                <td>{c.number ?? '—'}</td>
                <td className={c.programme_count === 0 ? styles.noGuide : undefined}>
                  {c.programme_count === 0 ? 'none' : c.programme_count}
                </td>
                <td>
                  <GuideKeyCell channel={c} sourceId={sourceId} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {pages > 1 ? (
        <div className={styles.pager}>
          <button
            type="button"
            className={styles.btn}
            disabled={page === 0}
            onClick={() => setPage((p) => p - 1)}
          >
            Prev
          </button>
          <span>
            Page {page + 1} of {pages}
          </span>
          <button
            type="button"
            className={styles.btn}
            disabled={page + 1 >= pages}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </button>
        </div>
      ) : null}
    </div>
  );
}
