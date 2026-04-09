import type { CollectionResponse, SeverityEnum, WatchStatusEnum } from './common';

export type WatchTypeEnum = 'persistent' | 'dynamic';

export interface WatchResponse {
  id: string;
  name: string;
  watch_type: WatchTypeEnum;
  status: WatchStatusEnum;
  region: string | null;
  country_codes: string[] | null;
  bounding_box: Record<string, number> | null;
  keywords: string[] | null;
  source_filter: string[] | null;
  severity_threshold: SeverityEnum;
  plan_id: string | null;
  ttl_hours: number | null;
  created_at: string;
  expires_at: string | null;
  promoted_at: string | null;
  created_by: string;
}

export type WatchList = CollectionResponse<WatchResponse>;
