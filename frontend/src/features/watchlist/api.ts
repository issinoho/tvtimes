import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, unwrap } from '@/lib/api/client';
import type { components } from '@/lib/api/schema';

export type WatchlistItem = components['schemas']['WatchlistItemOut'];

export function useWatchlist() {
  return useQuery({
    queryKey: ['watchlist'],
    queryFn: async () => unwrap(await api.GET('/api/watchlist')),
    staleTime: 30_000,
  });
}

export function useAddWatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (
      body: { kind: 'programme'; programme_id: string } | { kind: 'title'; title: string },
    ) => unwrap(await api.POST('/api/watchlist', { body: { lead_minutes: 15, ...body } })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['watchlist'] }),
  });
}

export function useRemoveWatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (itemId: string) =>
      unwrap(
        await api.DELETE('/api/watchlist/{item_id}', {
          params: { path: { item_id: itemId } },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['watchlist'] }),
  });
}
