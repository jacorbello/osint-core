import { queryOptions, useQuery, type UseQueryResult } from '@tanstack/react-query';
import { getDashboardSummary } from './dashboardApi';
import type { DashboardSummaryResponse } from '@/types/api/ui';

export const dashboardKeys = {
  all: ['dashboard'] as const,
  summary: () => [...dashboardKeys.all, 'summary'] as const,
};

export function dashboardSummaryQueryOptions() {
  return queryOptions({
    queryKey: dashboardKeys.summary(),
    queryFn: getDashboardSummary,
  });
}

export function useDashboardSummaryQuery() {
  return useQuery(dashboardSummaryQueryOptions());
}

export type UseDashboardSummaryQueryResult = UseQueryResult<DashboardSummaryResponse>;
