import { queryOptions, useQuery, type UseQueryResult } from '@tanstack/react-query';
import { getWatch, getWatches, type WatchesListParams } from './watchesApi';
import type { WatchList, WatchResponse } from '@/types/api/watch';

function normalizeObject<T extends object>(value: T): T {
  const entries = Object.entries(value).filter(([, item]) => item !== undefined);
  entries.sort(([left], [right]) => left.localeCompare(right));
  return Object.fromEntries(entries) as T;
}

export const watchesKeys = {
  all: ['watches'] as const,
  list: (params: WatchesListParams = {}) =>
    [...watchesKeys.all, 'list', normalizeObject(params)] as const,
  detail: (watchId: string) => [...watchesKeys.all, 'detail', watchId] as const,
};

export function watchesListQueryOptions(params: WatchesListParams = {}) {
  return queryOptions({
    queryKey: watchesKeys.list(params),
    queryFn: () => getWatches(params),
  });
}

export function watchDetailQueryOptions(watchId: string) {
  return queryOptions({
    queryKey: watchesKeys.detail(watchId),
    queryFn: () => getWatch(watchId),
    enabled: Boolean(watchId),
  });
}

export function useWatchesListQuery(params: WatchesListParams = {}) {
  return useQuery(watchesListQueryOptions(params));
}

export function useWatchDetailQuery(watchId: string) {
  return useQuery(watchDetailQueryOptions(watchId));
}

export type UseWatchesListQueryResult = UseQueryResult<WatchList>;
export type UseWatchDetailQueryResult = UseQueryResult<WatchResponse>;
