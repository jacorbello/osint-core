export interface PageInfo {
  offset: number;
  limit: number;
  total: number;
  has_more: boolean;
}

export interface CollectionResponse<T> {
  items: T[];
  page: PageInfo;
}

export interface FieldError {
  field: string | null;
  message: string;
  code: string | null;
}

export interface ProblemDetails {
  type?: string;
  title?: string;
  status?: number;
  code: string;
  detail: string;
  instance?: string | null;
  request_id?: string | null;
  errors?: FieldError[];
}

export type SeverityEnum = 'info' | 'low' | 'medium' | 'high' | 'critical';

export type StatusEnum = 'open' | 'acked' | 'escalated' | 'resolved';

export type JobStatusEnum = 'queued' | 'running' | 'succeeded' | 'failed' | 'partial_success' | 'dead_letter';

export type LeadStatusEnum = 'new' | 'reviewing' | 'qualified' | 'contacted' | 'retained' | 'declined' | 'stale';

export type WatchStatusEnum = 'active' | 'paused' | 'expired' | 'promoted';

export type RetentionClassEnum = 'ephemeral' | 'standard' | 'evidentiary';

export type ExportFormatEnum = 'csv' | 'json';
