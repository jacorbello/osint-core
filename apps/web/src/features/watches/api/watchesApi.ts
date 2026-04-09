import { apiClient } from '@/lib/api/client';
import type { WatchList, WatchResponse } from '@/types/api/watch';
import type { WatchStatusEnum } from '@/types/api/common';

export const watchesEndpointManifest = {
  list: { method: 'GET', path: '/api/v1/watches' },
  detail: { method: 'GET', path: '/api/v1/watches/{watch_id}' },
} as const;

export interface WatchesListParams {
  limit?: number;
  offset?: number;
  status?: WatchStatusEnum;
}

export async function getWatches(params: WatchesListParams = {}): Promise<WatchList> {
  const { data } = await apiClient.get<WatchList>('/api/v1/watches', { params });
  return data;
}

export async function getWatch(watchId: string): Promise<WatchResponse> {
  const { data } = await apiClient.get<WatchResponse>(`/api/v1/watches/${watchId}`);
  return data;
}
