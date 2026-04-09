import { cn } from '@/lib/utils/cn';
import { getSeverityColor } from '@/lib/utils/severity';
import type { SeverityEnum, StatusEnum } from '@/types/api/common';

const SEVERITIES: SeverityEnum[] = ['critical', 'high', 'medium', 'low', 'info'];
const STATUSES: StatusEnum[] = ['open', 'acked', 'escalated', 'resolved'];

interface AlertsFiltersProps {
  selectedSeverities: SeverityEnum[];
  onSeveritiesChange: (severities: SeverityEnum[]) => void;
  selectedStatus: StatusEnum | undefined;
  onStatusChange: (status: StatusEnum | undefined) => void;
}

export function AlertsFilters({
  selectedSeverities,
  onSeveritiesChange,
  selectedStatus,
  onStatusChange,
}: AlertsFiltersProps) {
  function toggleSeverity(severity: SeverityEnum) {
    if (selectedSeverities.includes(severity)) {
      onSeveritiesChange(selectedSeverities.filter((s) => s !== severity));
    } else {
      onSeveritiesChange([...selectedSeverities, severity]);
    }
  }

  function toggleStatus(status: StatusEnum) {
    onStatusChange(selectedStatus === status ? undefined : status);
  }

  return (
    <div className="flex flex-wrap items-center gap-6" data-testid="alerts-filters">
      <div className="flex items-center gap-2">
        <span className="text-xs font-label font-medium text-on-surface-variant uppercase tracking-wider">
          Severity
        </span>
        <div className="flex gap-1">
          {SEVERITIES.map((severity) => {
            const isActive = selectedSeverities.includes(severity);
            return (
              <button
                key={severity}
                data-testid={`severity-toggle-${severity}`}
                onClick={() => toggleSeverity(severity)}
                className={cn(
                  'px-2.5 py-1 rounded-md text-[11px] font-bold uppercase transition-all',
                  isActive
                    ? getSeverityColor(severity)
                    : 'bg-surface-container text-on-surface-variant hover:bg-surface-container-high'
                )}
              >
                {severity}
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex items-center gap-2">
        <span className="text-xs font-label font-medium text-on-surface-variant uppercase tracking-wider">
          Status
        </span>
        <div className="flex gap-1">
          {STATUSES.map((status) => {
            const isActive = selectedStatus === status;
            return (
              <button
                key={status}
                data-testid={`status-toggle-${status}`}
                onClick={() => toggleStatus(status)}
                className={cn(
                  'px-2.5 py-1 rounded-md text-[11px] font-bold uppercase transition-all',
                  isActive
                    ? 'bg-primary text-on-primary'
                    : 'bg-surface-container text-on-surface-variant hover:bg-surface-container-high'
                )}
              >
                {status}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
