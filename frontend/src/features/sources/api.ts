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
