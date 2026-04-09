import type { AlertResponse } from '@/types/api/alert';
import type { SeverityEnum } from '@/types/api/common';

const SEVERITY_WEIGHT: Record<SeverityEnum, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
  info: 4,
};

export function sortAlertsBySeverity(alerts: AlertResponse[]): AlertResponse[] {
  return [...alerts].sort((a, b) => {
    const weightDiff =
      (SEVERITY_WEIGHT[a.severity] ?? 4) - (SEVERITY_WEIGHT[b.severity] ?? 4);
    if (weightDiff !== 0) return weightDiff;
    return new Date(b.last_fired_at).getTime() - new Date(a.last_fired_at).getTime();
  });
}
