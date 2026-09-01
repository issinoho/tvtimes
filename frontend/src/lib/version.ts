import { useQuery } from '@tanstack/react-query';

import { api, unwrap } from '@/lib/api/client';

/** The running release, from `/api/healthz` — "dev" for a source build. */
export function useAppVersion() {
  return useQuery({
    queryKey: ['healthz'],
    queryFn: async () => unwrap(await api.GET('/api/healthz')),
    staleTime: Infinity,
    gcTime: Infinity,
  });
}
