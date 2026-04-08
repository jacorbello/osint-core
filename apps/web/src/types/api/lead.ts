import type { CollectionResponse, SeverityEnum } from './common';

export type LeadTypeEnum = 'incident' | 'policy';

export type LeadStatusEnum =
  | 'new'
  | 'reviewing'
  | 'qualified'
  | 'contacted'
  | 'retained'
  | 'declined'
  | 'stale';

export interface LeadResponse {
  id: string;
  lead_type: LeadTypeEnum;
  status: LeadStatusEnum;
  title: string;
  summary: string | null;
  constitutional_basis: string[];
  jurisdiction: string | null;
  institution: string | null;
  severity: SeverityEnum | null;
  confidence: number | null;
  dedupe_fingerprint: string;
  plan_id: string | null;
  event_ids: string[];
  entity_ids: string[];
  report_id: string | null;
  first_surfaced_at: string;
  last_updated_at: string;
  reported_at: string | null;
  created_at: string;
}

export type LeadList = CollectionResponse<LeadResponse>;

export interface LeadUpdateRequest {
  status: LeadStatusEnum;
}
