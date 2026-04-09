import { Link } from 'react-router-dom';
import { useAlertsQuery } from '@/features/alerts/api/alertsQueries';
import { getSeverityColor } from '@/lib/utils/severity';
import { formatRelativeTime } from '@/lib/utils/format';
import { cn } from '@/lib/utils/cn';
import { SkeletonBlock } from '@/components/feedback/SkeletonBlock';
import { EmptyState } from '@/components/feedback/EmptyState';
import { ErrorBanner } from '@/components/feedback/ErrorBanner';
import { sortAlertsBySeverity } from '../utils/sortAlerts';
import type { AlertResponse } from '@/types/api/alert';
import type { SeverityEnum, ProblemDetails } from '@/types/api/common';

const SEVERITY_BAR_COLOR: Record<string, string> = {
  critical: '#e06c75',
  high: '#e5c07b',
  medium: '#5b8def',
};

function getSeverityBarColor(severity: SeverityEnum): string | undefined {
  return SEVERITY_BAR_COLOR[severity];
}

function getSeverityBarClass(severity: SeverityEnum): string {
  if (severity === 'low' || severity === 'info') return 'bg-text-tertiary';
  return '';
}

const MAX_ALERTS = 7;

export function PriorityAlertsList() {
  const { data, isLoading, error } = useAlertsQuery({ limit: 20 });

  const sorted = data ? sortAlertsBySeverity(data.items).slice(0, MAX_ALERTS) : [];
  const totalCount = data?.page.total ?? 0;

  return (
    <div className="bg-surface-container-low rounded-lg border border-outline-variant/10 overflow-hidden flex flex-col h-[350px]">
      {/* Header */}
      <div className="p-4 border-b border-outline-variant/10 flex justify-between items-center flex-shrink-0">
        <h3 className="font-headline font-bold text-sm tracking-tight flex items-center gap-2 text-on-surface">
          <span
            className="material-symbols-outlined text-error text-lg"
            style={{ fontVariationSettings: "'FILL' 1" }}
          >
            priority_high
          </span>
          Priority Alerts
          {!isLoading && totalCount > 0 && (
            <span className="text-[10px] font-mono text-on-surface-variant bg-surface-container-high px-1.5 py-0.5 rounded">
              {totalCount}
            </span>
          )}
        </h3>
        <Link
          to="/alerts"
          className="text-[10px] font-bold text-primary uppercase hover:underline tracking-wider"
        >
          View all &rarr;
        </Link>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto">
        {isLoading && (
          <div className="p-3 flex flex-col gap-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <SkeletonBlock key={i} className="h-12 w-full" />
            ))}
          </div>
        )}

        {!isLoading && error && (
          <ErrorBanner error={error as unknown as ProblemDetails} className="m-3" />
        )}

        {!isLoading && !error && sorted.length === 0 && (
          <EmptyState
            icon="notifications_off"
            title="No alerts"
            description="No priority alerts to display right now"
            className="py-8"
          />
        )}

        {!isLoading && !error && sorted.length > 0 && (
          <ul className="divide-y divide-outline-variant/5">
            {sorted.map((alert) => (
              <AlertRow key={alert.id} alert={alert} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function AlertRow({ alert }: { alert: AlertResponse }) {
  const barColor = getSeverityBarColor(alert.severity);
  const barClass = getSeverityBarClass(alert.severity);

  return (
    <li className="relative flex items-center gap-3 px-4 py-2.5 hover:bg-surface-container-high/50 transition-colors">
      {/* Severity color bar */}
      <div
        className={cn('absolute left-0 top-0 bottom-0 w-[3px]', barClass)}
        style={barColor ? { backgroundColor: barColor } : undefined}
        data-testid={`severity-bar-${alert.severity}`}
      />

      {/* Title + metadata */}
      <div className="flex-1 min-w-0 pl-1">
        <p className="text-[12px] font-medium text-on-surface truncate">{alert.title}</p>
        <p className="text-[10px] text-on-surface-variant truncate">
          {alert.route_name && (
            <span className="font-medium">{alert.route_name} &middot; </span>
          )}
          <span>{formatRelativeTime(alert.last_fired_at)}</span>
          {alert.status === 'escalated' && (
            <span className="ml-1.5 text-error font-medium">Escalated</span>
          )}
        </p>
      </div>

      {/* Severity badge */}
      <span
        className={cn(
          'flex-shrink-0 px-1.5 py-0.5 rounded text-[9px] font-bold uppercase',
          getSeverityColor(alert.severity)
        )}
      >
        {alert.severity}
      </span>
    </li>
  );
}
