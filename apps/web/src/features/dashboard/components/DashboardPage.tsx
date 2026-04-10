import { useDashboardSummaryQuery } from '../api/dashboardQueries';
import { SummaryStrip } from './SummaryStrip';
import { MiniMap } from './MiniMap';
import { ActivityFeed } from './ActivityFeed';
import { PriorityAlertsList } from './PriorityAlertsList';
import { LeadsTableWidget } from './LeadsTableWidget';
import type { ProblemDetails } from '@/types/api/common';

export function DashboardPage() {
  const { data: summary, isLoading, error } = useDashboardSummaryQuery();

  const problemDetails = error as ProblemDetails | null;

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <SummaryStrip
        summary={
          summary || {
            alerts: {},
            leads: {},
            jobs: {},
            watches: {},
            events: { last_24h_count: 0 },
            updated_at: '',
          }
        }
        isLoading={isLoading}
        error={problemDetails}
      />

      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-4">
        {/* Map + activity rail row */}
        <div className="flex gap-4 flex-shrink-0">
          <div className="flex-1 min-w-0">
            <MiniMap />
          </div>
          <ActivityFeed />
        </div>

        {/* Table grid */}
        <div className="grid grid-cols-2 gap-4 flex-shrink-0">
          <PriorityAlertsList />
          <LeadsTableWidget />
        </div>
      </div>
    </div>
  );
}
