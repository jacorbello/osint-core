import { Link } from 'react-router-dom';
import { useAlertsQuery } from '@/features/alerts/api/alertsQueries';
import { getSeverityColor } from '@/lib/utils/severity';
import { formatRelativeTime } from '@/lib/utils/format';
import { cn } from '@/lib/utils/cn';
import { SkeletonBlock } from '@/components/feedback/SkeletonBlock';
import { ErrorBanner } from '@/components/feedback/ErrorBanner';
import { EmptyState } from '@/components/feedback/EmptyState';
import type { SeverityEnum, StatusEnum, ProblemDetails } from '@/types/api/common';

function StatusText({ status }: { status: StatusEnum }) {
  const colors: Record<StatusEnum, string> = {
    open: 'text-error',
    acked: 'text-tertiary-container',
    escalated: 'text-tertiary',
    resolved: 'text-on-surface-variant',
  };
  return (
    <span className={cn('text-[11px] font-medium', colors[status] ?? 'text-on-surface-variant')}>
      {status.toUpperCase()}
    </span>
  );
}

export function AlertsTableWidget() {
  const { data, isLoading, error } = useAlertsQuery({ limit: 10 });

  return (
    <div className="bg-surface-container-low rounded-lg border border-outline-variant/10 overflow-hidden flex flex-col h-[350px]">
      <div className="p-4 border-b border-outline-variant/10 flex justify-between items-center flex-shrink-0">
        <h3 className="font-headline font-bold text-sm tracking-tight flex items-center gap-2 text-on-surface">
          <span
            className="material-symbols-outlined text-error text-lg"
            style={{ fontVariationSettings: "'FILL' 1" }}
          >
            warning
          </span>
          System Alerts
        </h3>
        <Link
          to="/events"
          className="text-[10px] font-bold text-primary uppercase hover:underline tracking-wider"
        >
          View All
        </Link>
      </div>

      <div className="flex-1 overflow-auto">
        {isLoading && (
          <div className="p-3 flex flex-col gap-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <SkeletonBlock key={i} className="h-8 w-full" />
            ))}
          </div>
        )}

        {!isLoading && error && (
          <ErrorBanner error={error as unknown as ProblemDetails} className="m-3" />
        )}

        {!isLoading && !error && data?.items.length === 0 && (
          <EmptyState
            icon="notifications_off"
            title="No alerts"
            description="No alerts to display"
            className="py-8"
          />
        )}

        {!isLoading && !error && data && data.items.length > 0 && (
          <table className="w-full text-left border-collapse">
            <thead className="sticky top-0 bg-surface-container-high shadow-sm">
              <tr className="text-[9px] font-bold uppercase text-outline tracking-wider">
                <th className="px-4 py-2">Severity</th>
                <th className="px-4 py-2">Title</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2 text-right">Occurrences</th>
                <th className="px-4 py-2">Last Fired</th>
              </tr>
            </thead>
            <tbody className="text-[11px] divide-y divide-outline-variant/5">
              {data.items.map((alert, idx) => (
                <tr
                  key={alert.id}
                  className={cn(
                    'hover:bg-surface-container-high transition-colors',
                    idx % 2 === 0 ? 'bg-surface-container-lowest' : ''
                  )}
                >
                  <td className="px-4 py-3">
                    <span
                      className={cn(
                        'px-1.5 py-0.5 rounded text-[9px] font-bold',
                        getSeverityColor(alert.severity as SeverityEnum)
                      )}
                    >
                      {alert.severity.toUpperCase()}
                    </span>
                  </td>
                  <td className="px-4 py-3 font-medium text-on-surface max-w-[160px] truncate">
                    {alert.title}
                  </td>
                  <td className="px-4 py-3">
                    <StatusText status={alert.status} />
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-on-surface-variant">
                    {alert.occurrences.toLocaleString()}
                  </td>
                  <td className="px-4 py-3 text-outline whitespace-nowrap">
                    {formatRelativeTime(alert.last_fired_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
