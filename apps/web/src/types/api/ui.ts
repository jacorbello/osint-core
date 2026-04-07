export interface DashboardSummaryResponse {
  alerts: Record<string, number>;
  watches: Record<string, number>;
  leads: Record<string, number>;
  jobs: Record<string, number>;
  events: EventSummary;
  updated_at: string;
}

export interface EventSummary {
  last_24h_count: number;
}

export interface FacetBucket {
  value: string;
  count: number;
}

export interface FacetsResponse {
  facets: Record<string, FacetBucket[]>;
  applied_filters: Record<string, unknown>;
}

export type StreamEventType = 'alert.updated' | 'lead.updated' | 'job.updated';

export interface StreamEventPayload {
  type: StreamEventType;
  resource: string;
  id: string;
  timestamp: string;
  payload: Record<string, unknown>;
}
