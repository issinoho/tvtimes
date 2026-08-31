import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, unwrap } from '@/lib/api/client';
import type { components } from '@/lib/api/schema';

export type GuideOut = components['schemas']['GuideOut'];
export type GuideChannel = components['schemas']['GuideChannelOut'];
export type Programme = components['schemas']['ProgrammeOut'];
export type SearchHit = components['schemas']['SearchHitOut'];
/** A channel as it arrives on a search hit — no per-row programme list. */
export type SearchChannel = components['schemas']['SearchChannelOut'];

export interface GuideParams {
  from: string;
  to: string;
  source_id?: string;
  group?: string;
}

export function useGuide(params: GuideParams) {
  return useQuery({
    queryKey: ['guide', params],
    queryFn: async () => unwrap(await api.GET('/api/guide', { params: { query: params } })),
    staleTime: 60_000,
    placeholderData: (prev) => prev,
  });
}

export function useProgrammeSearch(query: string, moviesOnly: boolean) {
  const q = query.trim();
  return useQuery({
    queryKey: ['guide-search', q, moviesOnly],
    enabled: q.length >= 2,
    staleTime: 60_000,
    placeholderData: (prev) => prev,
    queryFn: async () =>
      unwrap(
        await api.GET('/api/guide/search', {
          params: { query: { q, movies_only: moviesOnly } },
        }),
      ),
  });
}

/**
 * Set a channel's per-channel clock offset (added to every one of its
 * programme times). Used to line up e.g. a US-West feed with an East-coast EPG.
 */
export function useSetChannelShift() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ channelId, seconds }: { channelId: string; seconds: number }) =>
      unwrap(
        await api.PATCH('/api/channels/{channel_id}', {
          params: { path: { channel_id: channelId } },
          body: { clock_shift_seconds: seconds },
        }),
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['guide'] });
      void qc.invalidateQueries({ queryKey: ['channel'] });
    },
  });
}
