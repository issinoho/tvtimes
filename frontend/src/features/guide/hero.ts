import { useQuery } from '@tanstack/react-query';

import { api, unwrap } from '@/lib/api/client';
import type { components } from '@/lib/api/schema';

export type HeroOut = components['schemas']['HeroOut'];

export function useHero(programmeId: string, enabled = true) {
  return useQuery({
    queryKey: ['hero', programmeId],
    enabled,
    queryFn: async () =>
      unwrap(
        await api.GET('/api/guide/programme/{programme_id}/hero', {
          params: { path: { programme_id: programmeId } },
        }),
      ),
    // While a cold enrichment is running, poll a few times.
    refetchInterval: (q) => (q.state.data?.enriching ? 2500 : false),
  });
}
