import {
  queryOptions,
  useMutation,
  useQuery,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';
import {
  exportEvents,
  getEvent,
  getEventFacets,
  getEventRelated,
  getEvents,
  type EventExportParams,
  type EventFacetsParams,
  type EventRelatedParams,
  type EventsListParams,
} from './eventsApi';
import type { FacetsResponse } from '@/types/api/ui';
import type { EventList, EventRelatedResponse, EventResponse } from '@/types/api/event';

function normalizeObject<T extends object>(value: T): T {
  const entries = Object.entries(value).filter(([, item]) => item !== undefined);
  entries.sort(([left], [right]) => left.localeCompare(right));
  return Object.fromEntries(entries) as T;
}

export const eventsKeys = {
  all: ['events'] as const,
  list: (params: EventsListParams = {}) =>
    [...eventsKeys.all, 'list', normalizeObject(params)] as const,
  facets: (params: EventFacetsParams = {}) =>
    [...eventsKeys.all, 'facets', normalizeObject(params)] as const,
  detail: (eventId: string) => [...eventsKeys.all, 'detail', eventId] as const,
  related: (eventId: string, params: EventRelatedParams = {}) => {
    const normalized = {
      include: params.include?.slice().sort((left, right) => left.localeCompare(right)).join(','),
    };
    return [...eventsKeys.all, 'related', eventId, normalizeObject(normalized)] as const;
  },
};

export function eventsListQueryOptions(params: EventsListParams = {}) {
  return queryOptions({
    queryKey: eventsKeys.list(params),
    queryFn: () => getEvents(params),
  });
}

export function eventFacetsQueryOptions(params: EventFacetsParams = {}) {
  return queryOptions({
    queryKey: eventsKeys.facets(params),
    queryFn: () => getEventFacets(params),
  });
}

export function eventDetailQueryOptions(eventId: string) {
  return queryOptions({
    queryKey: eventsKeys.detail(eventId),
    queryFn: () => getEvent(eventId),
    enabled: Boolean(eventId),
  });
}

export function eventRelatedQueryOptions(eventId: string, params: EventRelatedParams = {}) {
  return queryOptions({
    queryKey: eventsKeys.related(eventId, params),
    queryFn: () => getEventRelated(eventId, params),
    enabled: Boolean(eventId),
  });
}

export function useEventsListQuery(params: EventsListParams = {}) {
  return useQuery(eventsListQueryOptions(params));
}

export function useEventFacetsQuery(params: EventFacetsParams = {}) {
  return useQuery(eventFacetsQueryOptions(params));
}

export function useEventDetailQuery(eventId: string) {
  return useQuery(eventDetailQueryOptions(eventId));
}

export function useEventRelatedQuery(eventId: string, params: EventRelatedParams = {}) {
  return useQuery(eventRelatedQueryOptions(eventId, params));
}

export function useExportEventsMutation() {
  return useMutation({
    mutationFn: (params: EventExportParams = {}) => exportEvents(params),
  });
}

export type UseEventsListQueryResult = UseQueryResult<EventList>;
export type UseEventFacetsQueryResult = UseQueryResult<FacetsResponse>;
export type UseEventDetailQueryResult = UseQueryResult<EventResponse>;
export type UseEventRelatedQueryResult = UseQueryResult<EventRelatedResponse>;
export type UseExportEventsMutationResult = UseMutationResult<
  Blob | EventResponse[],
  Error,
  EventExportParams
>;
