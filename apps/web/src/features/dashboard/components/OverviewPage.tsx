import { useDashboardSummaryQuery } from '../api/dashboardQueries';
import { StatusCard, type BreakdownItem } from '@/components/data-display/StatusCard';
import { PriorityAlertsList } from './PriorityAlertsList';
import { LeadsTableWidget } from './LeadsTableWidget';
import { ActivityFeed } from './ActivityFeed';
import { MiniMap } from './MiniMap';
import { SkeletonBlock } from '@/components/feedback/SkeletonBlock';
import { ErrorBanner } from '@/components/feedback/ErrorBanner';
import type { ProblemDetails } from '@/types/api/common';
import type { DashboardSummaryResponse } from '@/types/api/ui';

function buildAlertBreakdowns(alerts: Record<string, number>): BreakdownItem[] {
  const items: BreakdownItem[] = [];
  if (alerts.open) items.push({ label: 'open', count: alerts.open, color: 'critical' });
  if (alerts.acked) items.push({ label: 'acked', count: alerts.acked, color: 'text-muted' });
  if (alerts.escalated) items.push({ label: 'escalated', count: alerts.escalated, color: 'warning' });
  return items;
}

function buildLeadBreakdowns(leads: Record<string, number>): BreakdownItem[] {
  const items: BreakdownItem[] = [];
  if (leads.new) items.push({ label: 'new', count: leads.new, color: 'primary' });
  if (leads.active) items.push({ label: 'active', count: leads.active, color: 'text-secondary' });
  return items;
}

function buildWatchBreakdowns(watches: Record<string, number>): BreakdownItem[] {
  const items: BreakdownItem[] = [];
  if (watches.active) items.push({ label: 'active', count: watches.active, color: 'success' });
  if (watches.paused) items.push({ label: 'paused', count: watches.paused, color: 'text-muted' });
  return items;
}

function buildJobBreakdowns(jobs: Record<string, number>): BreakdownItem[] {
  const items: BreakdownItem[] = [];
  if (jobs.running) items.push({ label: 'running', count: jobs.running, color: 'primary' });
  if (jobs.completed) items.push({ label: 'completed', count: jobs.completed, color: 'text-muted' });
  if (jobs.failed) items.push({ label: 'failed', count: jobs.failed, color: 'critical' });
  return items;
}

function sumValues(record: Record<string, number>): number {
  return Object.values(record).reduce((acc, v) => acc + v, 0);
}

function StatusCardsRow({
  summary,
  isLoading,
}: {
  summary: DashboardSummaryResponse | undefined;
  isLoading: boolean;
}) {
  if (isLoading) {
    return (
      <div className="grid grid-cols-4 gap-3" data-testid="status-cards-skeleton">
        {Array.from({ length: 4 }).map((_, i) => (
          <SkeletonBlock key={i} className="h-[72px] w-full" />
        ))}
      </div>
    );
  }

  if (!summary) return null;

  return (
    <div className="grid grid-cols-4 gap-3" data-testid="status-cards-row">
      <StatusCard
        label="Open Alerts"
        count={sumValues(summary.alerts)}
        breakdowns={buildAlertBreakdowns(summary.alerts)}
      />
      <StatusCard
        label="Active Leads"
        count={sumValues(summary.leads)}
        breakdowns={buildLeadBreakdowns(summary.leads)}
      />
      <StatusCard
        label="Active Watches"
        count={sumValues(summary.watches)}
        breakdowns={buildWatchBreakdowns(summary.watches)}
      />
      <StatusCard
        label="Jobs"
        count={sumValues(summary.jobs)}
        breakdowns={buildJobBreakdowns(summary.jobs)}
      />
    </div>
  );
}

export function OverviewPage() {
  const { data: summary, isLoading, error } = useDashboardSummaryQuery();

  const problemDetails = error as ProblemDetails | null;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Error banner */}
      {problemDetails && (
        <ErrorBanner error={problemDetails} className="m-4 mb-0" />
      )}

      {/* Status cards row */}
      <div className="p-4 pb-0 flex-shrink-0">
        <StatusCardsRow summary={summary} isLoading={isLoading} />
      </div>

      {/* Main content: two-column layout */}
      <div className="flex-1 flex gap-4 p-4 min-h-0">
        {/* Left column - scrollable */}
        <div className="flex-1 overflow-y-auto flex flex-col gap-4 min-w-0">
          <PriorityAlertsList />
          <LeadsTableWidget />
          <MiniMap />
        </div>

        {/* Right rail - ActivityFeed scrolls independently */}
        <ActivityFeed />
      </div>
    </div>
  );
}
