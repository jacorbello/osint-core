import { apiClient } from '@/lib/api/client';
import type { LeadList, LeadStatusEnum, LeadTypeEnum } from '@/types/api/lead';

export interface LeadsListParams {
  limit?: number;
  offset?: number;
  status?: LeadStatusEnum;
  jurisdiction?: string;
  lead_type?: LeadTypeEnum;
  plan_id?: string;
}

export async function getLeads(params: LeadsListParams = {}): Promise<LeadList> {
  const response = await apiClient.get<LeadList>('/api/v1/leads', { params });
  return response.data;
}
