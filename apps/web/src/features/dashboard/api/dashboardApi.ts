import { apiClient } from '@/lib/api/client';
import type { DashboardSummaryResponse } from '@/types/api/ui';

export async function getDashboardSummary(): Promise<DashboardSummaryResponse> {
  const { data } = await apiClient.get<DashboardSummaryResponse>('/api/v1/dashboard/summary');
  return data;
}
