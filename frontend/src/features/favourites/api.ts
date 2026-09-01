import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, unwrap } from '@/lib/api/client';

const KEY = ['favourites'];

/** The user's favourite channel ids as a Set. */
export function useFavourites() {
  return useQuery({
    queryKey: KEY,
    queryFn: async () => new Set<string>(unwrap(await api.GET('/api/favourites')).channel_ids),
    staleTime: 60_000,
  });
}

export function useToggleFavourite() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ channelId, on }: { channelId: string; on: boolean }) => {
      if (on) {
        unwrap(await api.POST('/api/favourites', { body: { channel_id: channelId } }));
      } else {
        unwrap(
          await api.DELETE('/api/favourites/{channel_id}', {
            params: { path: { channel_id: channelId } },
          }),
        );
      }
    },
    onMutate: async ({ channelId, on }) => {
      await qc.cancelQueries({ queryKey: KEY });
      const prev = qc.getQueryData<Set<string>>(KEY);
      const next = new Set(prev ?? []);
      if (on) next.add(channelId);
      else next.delete(channelId);
      qc.setQueryData(KEY, next);
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(KEY, ctx.prev);
    },
    onSettled: () => void qc.invalidateQueries({ queryKey: KEY }),
  });
}
