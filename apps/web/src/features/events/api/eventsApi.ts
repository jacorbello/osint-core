import { apiClient } from '@/lib/api/client';
import type { ExportFormatEnum } from '@/types/api/common';
import type { EventList, EventRelatedResponse, EventResponse } from '@/types/api/event';
import type { FacetsResponse } from '@/types/api/ui';

export const eventsEndpointManifest = {
  list: { method: 'GET', path: '/api/v1/events' },
  facets: { method: 'GET', path: '/api/v1/events/facets' },
  detail: { method: 'GET', path: '/api/v1/events/{event_id}' },
  related: { method: 'GET', path: '/api/v1/events/{event_id}/related' },
  export: { method: 'GET', path: '/api/v1/events/export' },
} as const;

export type EventSortField = 'ingested_at' | 'occurred_at' | 'score';
export type EventSort = EventSortField | `-${EventSortField}`;

export interface EventsListParams {
  limit?: number;
  offset?: number;
  source_id?: string;
  severity?: string;
  date_from?: string;
  date_to?: string;
  attack_technique?: string;
  sort?: EventSort;
}

export interface EventFacetsParams {
  source_id?: string;
  severity?: string;
  date_from?: string;
  date_to?: string;
  attack_technique?: string;
}

export interface EventRelatedParams {
  include?: Array<'alerts' | 'entities' | 'indicators'>;
}

export interface EventExportParams extends EventsListParams {
  format?: ExportFormatEnum;
}

export async function getEvents(params: EventsListParams = {}): Promise<EventList> {
  const { data } = await apiClient.get<EventList>('/api/v1/events', { params });
  return data;
}

export async function getEventFacets(params: EventFacetsParams = {}): Promise<FacetsResponse> {
  const { data } = await apiClient.get<FacetsResponse>('/api/v1/events/facets', { params });
  return data;
}

export async function getEvent(eventId: string): Promise<EventResponse> {
  const { data } = await apiClient.get<EventResponse>(`/api/v1/events/${eventId}`);
  return data;
}

export async function getEventRelated(
  eventId: string,
  params: EventRelatedParams = {}
): Promise<EventRelatedResponse> {
  const include = params.include?.join(',');
  const { data } = await apiClient.get<EventRelatedResponse>(`/api/v1/events/${eventId}/related`, {
    params: include ? { include } : undefined,
  });
  return data;
}

export async function exportEvents(
  params: EventExportParams = {}
): Promise<Blob | EventResponse[]> {
  const format = params.format ?? 'csv';
  const responseType = format === 'json' ? 'json' : 'blob';
  const { data } = await apiClient.get<Blob | EventResponse[]>('/api/v1/events/export', {
    params: { ...params, format },
    responseType,
  });
  return data;
}
