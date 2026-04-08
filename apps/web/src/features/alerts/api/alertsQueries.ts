import { queryOptions, useQuery, type UseQueryResult } from '@tanstack/react-query';
import { getAlerts, type AlertsListParams } from './alertsApi';
import type { AlertList } from '@/types/api/alert';

function normalizeParams(params: AlertsListParams): string {
  return Object.entries(params)
    .filter(([, v]) => v !== undefined)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, v]) => `${k}=${String(v)}`)
    .join('&');
}

export const alertsKeys = {
  all: ['alerts'] as const,
  list: (params: AlertsListParams = {}) =>
    [...alertsKeys.all, 'list', normalizeParams(params)] as const,
};

export function alertsListQueryOptions(params: AlertsListParams = {}) {
  return queryOptions({
    queryKey: alertsKeys.list(params),
    queryFn: () => getAlerts(params),
  });
}

export function useAlertsQuery(params: AlertsListParams = {}) {
  return useQuery(alertsListQueryOptions(params));
}

export type UseAlertsQueryResult = UseQueryResult<AlertList>;
