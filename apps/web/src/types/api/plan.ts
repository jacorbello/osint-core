import { CollectionResponse } from './common';

export interface PlanVersion {
  id: string;
  plan_id: string;
  version: number;
  content_hash: string;
  content: Record<string, any>;
  retention_class: string;
  git_commit_sha: string | null;
  validation_result: Record<string, any>;
  is_active: boolean;
  created_at: string;
  created_by: string;
  activated_at: string | null;
  activated_by: string | null;
}

export interface PlanVersionResponse extends PlanVersion {}

export type PlanVersionList = CollectionResponse<PlanVersionResponse>;

export interface PlanValidationResult {
  is_valid: boolean;
  errors: string[];
  warnings: string[];
}

export interface PlanCreateRequest {
  yaml: string;
  git_commit_sha?: string;
  activate?: boolean;
}

export interface PlanActivationRequest {
  version_id?: string;
  rollback?: boolean;
}
