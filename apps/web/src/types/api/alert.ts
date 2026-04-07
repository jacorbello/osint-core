import type { CollectionResponse, SeverityEnum, StatusEnum } from './common';

export interface AlertResponse {
  id: string;
  fingerprint: string;
  severity: SeverityEnum;
  title: string;
  summary: string | null;
  event_ids: string[];
  indicator_ids: string[];
  entity_ids: string[];
  route_name: string | null;
  status: StatusEnum;
  occurrences: number;
  first_fired_at: string;
  last_fired_at: string;
  acked_at: string | null;
  acked_by: string | null;
  plan_version_id: string | null;
  created_at: string;
}

export type AlertList = CollectionResponse<AlertResponse>;

export interface AlertUpdateRequest {
  status: StatusEnum;
}

export interface AlertBulkUpdateRequest {
  ids: string[];
  target_status: StatusEnum;
  dry_run?: boolean;
}
