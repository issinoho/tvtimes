import { useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';

import { ChannelLogo } from '@/features/guide/ChannelLogo';
import { EditSourceDialog } from '@/features/sources/EditSourceDialog';
import { EpgPanel } from '@/features/sources/EpgPanel';
import { StatusPill } from '@/features/sources/StatusPill';
import { UrlUpdatesPanel } from '@/features/sources/UrlUpdatesPanel';
import {
  useChannels,
  useDeleteSource,
  usePatchSource,
  useChannelGroups,
  usePatchChannel,
  useRefreshSource,
  useSource,
  type ChannelPatch,
} from '@/features/sources/api';
import styles from '@/features/sources/sources.module.css';
import type { components } from '@/lib/api/schema';

type Channel = components['schemas']['ChannelOut'];

const PAGE = 50;

const GROUPS_LIST = 'channel-groups';

/**
 * One hand-set override on the channel table, edited in place: an input that
 * reads as text until touched, saving on Enter or when focus leaves, and only
 * if the value changed. Empty clears the override; the placeholder shows what
 * the channel falls back to then.
 */
function OverrideCell({
  label,
  saved,
  placeholder,
  onSave,
  pending,
  list,
  wide,
}: {
  label: string;
  saved: string;
  placeholder: string;
  onSave: (value: string) => void;
  pending: boolean;
  list?: string;
  wide?: boolean;
}) {
  const [value, setValue] = useState(saved);
  const save = () => {
    if (value.trim() !== saved) onSave(value);
  };
  return (
    <form
      className={wide ? `${styles.guideKey} ${styles.wide}` : styles.guideKey}
      onSubmit={(e) => {
        e.preventDefault();
        save();
      }}
    >
      <input
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onBlur={save}
        placeholder={placeholder}
        aria-label={label}
        list={list}
        disabled={pending}
      />
    </form>
  );
}

/**
 * The per-channel overrides: the guide key (only earns its keep for a channel
 * showing 0 programmes -- its own tvg-id and names found nothing in the
 * guide), the category, and the logo URL. Category and logo apply at once and
 * survive source refreshes, which otherwise rewrite both from the feed.
 */
function ChannelOverrides({ channel, sourceId }: { channel: Channel; sourceId: string }) {
  const patch = usePatchChannel(sourceId);
  const save = (body: ChannelPatch) => patch.mutate({ channelId: channel.id, body });
  const pending = patch.isPending;
  return (
    <>
      <td>
        <OverrideCell
          label={`Category for ${channel.name}`}
          saved={channel.group_override ?? ''}
          placeholder={channel.upstream_group_title ?? '—'}
          onSave={(v) => save({ group_override: v })}
          pending={pending}
          list={GROUPS_LIST}
        />
      </td>
      <td>{channel.number ?? '—'}</td>
      <td className={channel.programme_count === 0 ? styles.noGuide : undefined}>
        {channel.programme_count === 0 ? 'none' : channel.programme_count}
      </td>
      <td>
        <OverrideCell
          label={`Guide key for ${channel.name}`}
          saved={channel.epg_override_id ?? ''}
          placeholder={channel.ext_id ?? '—'}
          onSave={(v) => save({ epg_override_id: v })}
          pending={pending}
        />
      </td>
      <td>
        <OverrideCell
          label={`Logo URL for ${channel.name}`}
          saved={channel.logo_override ?? ''}
          placeholder={channel.upstream_logo_url ? 'from source' : 'Paste image URL'}
          onSave={(v) => save({ logo_override: v })}
          pending={pending}
          wide
        />
        {patch.error ? (
          <div className={styles.cellError} role="alert">
            {patch.error instanceof Error ? patch.error.message : 'Could not save'}
          </div>
        ) : null}
      </td>
    </>
  );
}

export function SourceDetailPage() {
  const { sourceId = '' } = useParams();
  const navigate = useNavigate();
  const { data: source, isPending } = useSource(sourceId);
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const groups = useChannelGroups();
  const channels = useChannels(sourceId, {
    search: search || undefined,
    limit: PAGE,
    offset: page * PAGE,
  });

  const refresh = useRefreshSource();
  const remove = useDeleteSource();
  const patch = usePatchSource(sourceId);
  const [editing, setEditing] = useState(false);

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

      <EpgPanel sourceId={sourceId} advertised={source.advertised_epg_urls} />
      <UrlUpdatesPanel source={source} />

      <div className={styles.toolbar}>
        <button
          type="button"
          className={styles.btn}
          onClick={() => refresh.mutate(sourceId)}
          disabled={refresh.isPending || source.last_status === 'pending'}
        >
          {source.last_status === 'pending' ? 'Refreshing…' : 'Refresh now'}
        </button>
        <button type="button" className={styles.btn} onClick={() => setEditing(true)}>
          Edit
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
      {editing ? <EditSourceDialog source={source} onClose={() => setEditing(false)} /> : null}

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

      {/* One list for every Category cell: the categories already on the
          account, so "Sports" is one keystroke, while a new name still goes. */}
      <datalist id={GROUPS_LIST}>
        {(groups.data ?? []).map((g) => (
          <option key={g} value={g} />
        ))}
      </datalist>
      <div style={{ overflowX: 'auto' }}>
        <table className={styles.channels}>
          <thead>
            <tr>
              <th />
              <th>Name</th>
              <th>Category</th>
              <th>No.</th>
              <th>Guide</th>
              <th>Guide key</th>
              <th>Logo URL</th>
            </tr>
          </thead>
          <tbody>
            {(channels.data?.items ?? []).map((c) => (
              <tr key={c.id}>
                <td>
                  {/* Through the proxy, like every other logo in the app: these
                      URLs are usually http:// on a LAN, which an https page
                      blocks outright. */}
                  <ChannelLogo
                    channelId={c.id}
                    hasLogo={Boolean(c.logo_url)}
                    imgClassName={styles.logo}
                    emptyClassName={styles.logoEmpty}
                  />
                </td>
                <td>
                  {c.name}
                  {c.is_hd ? <span className={styles.kindTag}> HD</span> : null}
                </td>
                <ChannelOverrides channel={c} sourceId={sourceId} />
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
