import { queryOptions, useQuery, type UseQueryResult } from '@tanstack/react-query';
import { getLeads, type LeadsListParams } from './leadsApi';
import type { LeadList } from '@/types/api/lead';

function normalizeParams(params: LeadsListParams): string {
  return Object.entries(params)
    .filter(([, v]) => v !== undefined)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, v]) => `${k}=${String(v)}`)
    .join('&');
}

export const leadsKeys = {
  all: ['leads'] as const,
  list: (params: LeadsListParams = {}) =>
    [...leadsKeys.all, 'list', normalizeParams(params)] as const,
};

export function leadsListQueryOptions(params: LeadsListParams = {}) {
  return queryOptions({
    queryKey: leadsKeys.list(params),
    queryFn: () => getLeads(params),
  });
}

export function useLeadsQuery(params: LeadsListParams = {}) {
  return useQuery(leadsListQueryOptions(params));
}

export type UseLeadsQueryResult = UseQueryResult<LeadList>;
