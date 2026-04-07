import { CollectionResponse } from './common';

export interface PlanVersion {
  id: string;
  plan_id: string;
  version: number;
  content_hash: string;
  content: Record<string, unknown>;
  retention_class: string;
  git_commit_sha: string | null;
  validation_result: Record<string, unknown>;
  is_active: boolean;
  created_at: string;
  created_by: string;
  activated_at: string | null;
  activated_by: string | null;
}

export type PlanVersionResponse = PlanVersion;

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
