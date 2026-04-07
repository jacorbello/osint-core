import { apiClient } from '@/lib/api/client';
import type { AlertList } from '@/types/api/alert';
import type { SeverityEnum, StatusEnum } from '@/types/api/common';

export interface AlertsListParams {
  limit?: number;
  offset?: number;
  status?: StatusEnum;
  severity?: SeverityEnum;
}

export async function getAlerts(params: AlertsListParams = {}): Promise<AlertList> {
  const response = await apiClient.get<AlertList>('/api/v1/alerts', { params });
  return response.data;
}
