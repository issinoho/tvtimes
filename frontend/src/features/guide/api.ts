import { useQuery } from '@tanstack/react-query';

import { api, unwrap } from '@/lib/api/client';
import type { components } from '@/lib/api/schema';

export type GuideOut = components['schemas']['GuideOut'];
export type GuideChannel = components['schemas']['GuideChannelOut'];
export type Programme = components['schemas']['ProgrammeOut'];

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
