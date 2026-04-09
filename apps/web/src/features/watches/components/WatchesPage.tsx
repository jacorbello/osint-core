import { useWatchesListQuery } from '../api/watchesQueries';
import { SkeletonTable } from '@/components/feedback/SkeletonTable';
import { EmptyState } from '@/components/feedback/EmptyState';
import { ErrorBanner } from '@/components/feedback/ErrorBanner';
import { cn } from '@/lib/utils/cn';
import type { WatchResponse } from '@/types/api/watch';
import type { ProblemDetails, WatchStatusEnum } from '@/types/api/common';

const STATUS_CONFIG: Record<WatchStatusEnum, { label: string; color: string }> = {
  active: { label: 'Active', color: 'bg-success' },
  paused: { label: 'Paused', color: 'bg-warning' },
  expired: { label: 'Expired', color: 'bg-error' },
  promoted: { label: 'Promoted', color: 'bg-primary' },
};

function StatusIndicator({ status }: { status: WatchStatusEnum }) {
  const config = STATUS_CONFIG[status];
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={cn('w-2 h-2 rounded-full', config.color)}
        data-testid={`status-dot-${status}`}
      />
      <span className="text-sm text-on-surface">{config.label}</span>
    </span>
  );
}

function formatDateTime(iso: string | null): string {
  if (!iso) return '\u2014';
  const date = new Date(iso);
  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function WatchRow({ watch }: { watch: WatchResponse }) {
  return (
    <tr className="border-b border-outline-variant/10 hover:bg-surface-container-low/50 transition-colors" data-testid="watch-row">
      <td className="py-3 px-4">
        <span className="text-sm font-medium text-on-surface">{watch.name}</span>
      </td>
      <td className="py-3 px-4">
        <span className="text-sm text-on-surface-variant capitalize">{watch.watch_type}</span>
      </td>
      <td className="py-3 px-4">
        <StatusIndicator status={watch.status} />
      </td>
      <td className="py-3 px-4">
        <span className="text-sm text-on-surface-variant">{watch.severity_threshold}</span>
      </td>
      <td className="py-3 px-4">
        <span className="text-sm text-on-surface-variant">{formatDateTime(watch.created_at)}</span>
      </td>
      <td className="py-3 px-4">
        <span className="text-sm text-on-surface-variant">
          {watch.keywords?.length ?? 0} keywords
        </span>
      </td>
    </tr>
  );
}

function WatchesTable({ watches }: { watches: WatchResponse[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-outline-variant/10 bg-surface-container-low">
      <table className="w-full" data-testid="watches-table">
        <thead>
          <tr className="border-b border-outline-variant/20">
            <th className="text-left py-3 px-4 text-xs font-label font-medium text-on-surface-variant uppercase tracking-wider">Name</th>
            <th className="text-left py-3 px-4 text-xs font-label font-medium text-on-surface-variant uppercase tracking-wider">Type</th>
            <th className="text-left py-3 px-4 text-xs font-label font-medium text-on-surface-variant uppercase tracking-wider">Status</th>
            <th className="text-left py-3 px-4 text-xs font-label font-medium text-on-surface-variant uppercase tracking-wider">Severity</th>
            <th className="text-left py-3 px-4 text-xs font-label font-medium text-on-surface-variant uppercase tracking-wider">Created</th>
            <th className="text-left py-3 px-4 text-xs font-label font-medium text-on-surface-variant uppercase tracking-wider">Scope</th>
          </tr>
        </thead>
        <tbody>
          {watches.map((watch) => (
            <WatchRow key={watch.id} watch={watch} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function WatchesPage() {
  const { data, isLoading, error } = useWatchesListQuery();

  const problemDetails = error as ProblemDetails | null;
  const watches = data?.items ?? [];

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Error banner */}
      {problemDetails && (
        <ErrorBanner error={problemDetails} className="m-4 mb-0" />
      )}

      {/* Header with action */}
      <div className="flex items-center justify-between p-4 pb-0 flex-shrink-0">
        <div>
          <h2 className="text-lg font-headline font-semibold text-on-surface">Watches</h2>
          <p className="text-sm text-on-surface-variant mt-0.5">
            Monitor targets and track collection requirements.
          </p>
        </div>
        <button
          type="button"
          className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg bg-primary text-on-primary text-sm font-label font-medium hover:bg-primary/90 transition-colors"
          data-testid="create-watch-button"
        >
          <span className="material-symbols-outlined text-[18px]">add</span>
          New Watch
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4">
        {isLoading && (
          <div data-testid="watches-skeleton">
            <SkeletonTable rows={5} columns={6} />
          </div>
        )}

        {!isLoading && !error && watches.length === 0 && (
          <EmptyState
            icon="visibility"
            title="No watches yet"
            description="Watches monitor specific targets, regions, or keywords and surface matching events automatically. Create your first watch to start collecting intelligence."
            action={
              <button
                type="button"
                className="inline-flex items-center gap-1.5 h-8 px-4 rounded-lg bg-primary text-on-primary text-sm font-label font-medium hover:bg-primary/90 transition-colors"
                data-testid="empty-create-watch-button"
              >
                <span className="material-symbols-outlined text-[18px]">add</span>
                Create a Watch
              </button>
            }
          />
        )}

        {!isLoading && !error && watches.length > 0 && (
          <WatchesTable watches={watches} />
        )}
      </div>
    </div>
  );
}
