import { cn } from '@/lib/utils/cn';
import type { ProblemDetails } from '@/types/api/common';
import type { DashboardSummaryResponse } from '@/types/api/ui';
import { SummaryMetricCard } from './SummaryMetricCard';
import { ErrorBanner } from '@/components/feedback/ErrorBanner';
import { SkeletonBlock } from '@/components/feedback/SkeletonBlock';

interface SummaryStripProps {
  summary: DashboardSummaryResponse;
  isLoading?: boolean;
  error?: ProblemDetails | null;
  className?: string;
}

export function SummaryStrip({ summary, isLoading, error, className }: SummaryStripProps) {
  if (error) {
    return <ErrorBanner error={error} className="m-4" />;
  }

  if (isLoading) {
    return (
      <div className={cn('flex items-center gap-6 px-6 py-4 bg-surface-container-low', className)}>
        <SkeletonBlock className="h-8 w-32" />
        <SkeletonBlock className="h-8 w-32" />
        <SkeletonBlock className="h-8 w-32" />
        <SkeletonBlock className="h-8 w-32" />
      </div>
    );
  }

  return (
    <div
      className={cn(
        'flex items-center gap-6 px-6 py-4 bg-surface-container-low overflow-x-auto',
        className
      )}
    >
      <SummaryMetricCard label="Alerts" counts={summary.alerts} variant="alerts" />
      <SummaryMetricCard label="Leads" counts={summary.leads} variant="leads" />
      <SummaryMetricCard label="Jobs" counts={summary.jobs} variant="jobs" />
      <SummaryMetricCard label="Watches" counts={summary.watches} />
      <SummaryMetricCard
        label="Events (24h)"
        counts={{ total: summary.events.last_24h_count }}
        variant="events"
      />
    </div>
  );
}
