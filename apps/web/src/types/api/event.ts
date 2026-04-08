import { CollectionResponse, SeverityEnum } from './common';

export interface Event {
  id: string;
  event_type: string;
  source_id: string;
  title: string | null;
  summary: string | null;
  raw_excerpt: string | null;
  occurred_at: string | null;
  ingested_at: string;
  score: number | null;
  severity: SeverityEnum | null;
  dedupe_fingerprint: string;
  plan_version_id: string | null;
  country_code: string | null;
  latitude: number | null;
  longitude: number | null;
  region: string | null;
  source_category: string | null;
  nlp_relevance: string | null;
  nlp_summary: string | null;
  metadata: Record<string, unknown>;
}

export type EventResponse = Event;

export type EventList = CollectionResponse<EventResponse>;

export interface EventSearchList extends EventList {
  retrieval_mode: string;
}

export interface AlertRelated {
  id: string;
  fingerprint: string;
  severity: SeverityEnum;
  title: string;
  summary: string | null;
  event_ids: string[];
  indicator_ids: string[];
  entity_ids: string[];
  route_name: string | null;
  status: 'open' | 'acked' | 'escalated' | 'resolved';
  occurrences: number;
  first_fired_at: string;
  last_fired_at: string;
  acked_at: string | null;
  acked_by: string | null;
  plan_version_id: string | null;
  created_at: string;
}

export interface EntityRelated {
  id: string;
  entity_type: string;
  name: string;
  aliases: string[];
  attributes: Record<string, unknown>;
  first_seen: string;
  last_seen: string;
  created_at: string;
}

export interface IndicatorRelated {
  id: string;
  indicator_type: string;
  value: string;
  confidence: number;
  first_seen: string;
  last_seen: string;
  sources: string[];
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface EventRelatedMeta {
  alert_count: number;
  entity_count: number;
  indicator_count: number;
}

export interface EventRelatedResponse {
  event: EventResponse;
  alerts: AlertRelated[];
  entities: EntityRelated[];
  indicators: IndicatorRelated[];
  meta: EventRelatedMeta;
}
