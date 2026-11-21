import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, unwrap } from '@/lib/api/client';
import type { components } from '@/lib/api/schema';

export type SourceOut = components['schemas']['SourceOut'];
export type ChannelOut = components['schemas']['ChannelOut'];
export type SourceKind = 'm3u' | 'xtream' | 'stalker' | 'hdhomerun';

export type SourceCreate =
  | components['schemas']['M3uSourceIn']
  | components['schemas']['XtreamSourceIn']
  | components['schemas']['StalkerSourceIn']
  | components['schemas']['HdhomerunSourceIn'];

export function useSources() {
  return useQuery({
    queryKey: ['sources'],
    queryFn: async () => unwrap(await api.GET('/api/sources')),
    refetchInterval: (q) =>
      (q.state.data ?? []).some((s) => s.last_status === 'pending') ? 3000 : false,
  });
}

export function useSource(id: string) {
  return useQuery({
    queryKey: ['sources', id],
    queryFn: async () =>
      unwrap(await api.GET('/api/sources/{source_id}', { params: { path: { source_id: id } } })),
    refetchInterval: (q) => (q.state.data?.last_status === 'pending' ? 3000 : false),
  });
}

export function useChannels(
  id: string,
  params: { search?: string; group?: string; limit?: number; offset?: number },
) {
  return useQuery({
    queryKey: ['sources', id, 'channels', params],
    queryFn: async () =>
      unwrap(
        await api.GET('/api/sources/{source_id}/channels', {
          params: { path: { source_id: id }, query: params },
        }),
      ),
  });
}

export function useCreateSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: SourceCreate) => unwrap(await api.POST('/api/sources', { body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sources'] }),
  });
}

export function usePatchSource(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: components['schemas']['SourcePatchIn']) =>
      unwrap(
        await api.PATCH('/api/sources/{source_id}', {
          params: { path: { source_id: id } },
          body,
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sources'] }),
  });
}

export function useDeleteSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.DELETE('/api/sources/{source_id}', { params: { path: { source_id: id } } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sources'] }),
  });
}

/** Persist the source order shown on the Sources screen (also reorders the guide). */
export function useReorderSources() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (ids: string[]) =>
      unwrap(await api.PUT('/api/sources/order', { body: { ids } })),
    onMutate: async (ids) => {
      await qc.cancelQueries({ queryKey: ['sources'] });
      const prev = qc.getQueryData<SourceOut[]>(['sources']);
      if (prev) {
        const byId = new Map(prev.map((s) => [s.id, s]));
        qc.setQueryData<SourceOut[]>(
          ['sources'],
          ids.map((id) => byId.get(id)).filter((s): s is SourceOut => Boolean(s)),
        );
      }
      return { prev };
    },
    onError: (_err, _ids, ctx) => {
      if (ctx?.prev) qc.setQueryData(['sources'], ctx.prev);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ['sources'] });
      void qc.invalidateQueries({ queryKey: ['guide'] });
    },
  });
}

export function useRefreshSource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST('/api/sources/{source_id}/refresh', {
          params: { path: { source_id: id } },
        }),
      ),
    onSuccess: (_d, id) => {
      void qc.invalidateQueries({ queryKey: ['sources'] });
      void qc.invalidateQueries({ queryKey: ['sources', id] });
    },
  });
}

export type ChannelPatch = components['schemas']['ChannelPatchIn'];

/**
 * Set (or clear, with an empty string) a channel's hand-set overrides:
 *
 * - `epg_override_id`: the guide key it's matched on, for a channel whose own
 *   tvg-id and names find nothing (a tuner numbering BBC One Scotland HD 101
 *   where the guide carries it as 1). Takes effect on the next guide refresh.
 * - `group_override` / `logo_override`: the category and logo URL to show
 *   whatever the source says. Applied at once and kept across refreshes.
 */
export function usePatchChannel(sourceId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ channelId, body }: { channelId: string; body: ChannelPatch }) =>
      unwrap(
        await api.PATCH('/api/channels/{channel_id}', {
          params: { path: { channel_id: channelId } },
          body,
        }),
      ),
    onSuccess: (_d, { body }) => {
      void qc.invalidateQueries({ queryKey: ['sources', sourceId, 'channels'] });
      void qc.invalidateQueries({ queryKey: ['guide'] });
      if (body.group_override !== undefined)
        void qc.invalidateQueries({ queryKey: ['channel-groups'] });
    },
  });
}

/** Every category in use on the account, suggested when setting one by hand. */
export function useChannelGroups() {
  return useQuery({
    queryKey: ['channel-groups'],
    queryFn: async () => unwrap(await api.GET('/api/channels/groups')),
    staleTime: 60_000,
  });
}
