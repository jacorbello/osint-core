import { CollectionResponse } from './common';

export interface Brief {
  id: string;
  title: string;
  content_md: string;
  content_pdf_uri: string | null;
  target_query: string;
  generated_by: string;
  model_id: string;
  requested_by: string;
  created_at: string;
  event_ids: string[];
  entity_ids: string[];
  indicator_ids: string[];
}

export interface BriefResponse extends Brief {}

export type BriefList = CollectionResponse<BriefResponse>;

export interface BriefCreateRequest {
  query: string;
}
