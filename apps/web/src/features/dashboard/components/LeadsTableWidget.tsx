import { useLeadsQuery } from '@/features/leads/api/leadsQueries';
import { formatRelativeTime } from '@/lib/utils/format';
import { cn } from '@/lib/utils/cn';
import { SkeletonBlock } from '@/components/feedback/SkeletonBlock';
import { ErrorBanner } from '@/components/feedback/ErrorBanner';
import { EmptyState } from '@/components/feedback/EmptyState';
import type { LeadStatusEnum } from '@/types/api/lead';
import type { ProblemDetails } from '@/types/api/common';


function StatusText({ status }: { status: LeadStatusEnum }) {
  const colors: Partial<Record<LeadStatusEnum, string>> = {
    new: 'text-primary',
    reviewing: 'text-secondary',
    qualified: 'text-on-secondary-container',
    contacted: 'text-tertiary-container',
    retained: 'text-on-primary-container',
    declined: 'text-error',
    stale: 'text-on-surface-variant',
  };
  return (
    <span className={cn('text-[11px] font-medium', colors[status] ?? 'text-on-surface-variant')}>
      {status.toUpperCase()}
    </span>
  );
}

function ConfidenceBar({ confidence }: { confidence: number | null }) {
  if (confidence === null) {
    return <span className="text-[9px] text-outline">—</span>;
  }
  const pct = Math.round(confidence * 100);
  const fillColor = pct >= 70 ? 'bg-primary-container' : 'bg-tertiary-container';

  return (
    <div className="flex items-center gap-2">
      <div className="w-10 h-1.5 bg-surface-container-high rounded overflow-hidden">
        <div className={cn('h-full rounded', fillColor)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[9px] text-on-surface-variant">{pct}%</span>
    </div>
  );
}

export function LeadsTableWidget() {
  const { data, isLoading, error } = useLeadsQuery({ limit: 10 });

  return (
    <div className="bg-surface-container-low rounded-lg border border-outline-variant/10 overflow-hidden flex flex-col h-[350px]">
      <div className="p-4 border-b border-outline-variant/10 flex justify-between items-center flex-shrink-0">
        <h3 className="font-headline font-bold text-sm tracking-tight flex items-center gap-2 text-on-surface">
          <span className="material-symbols-outlined text-primary text-lg">person_pin_circle</span>
          High Value Leads
        </h3>
        <button className="text-[10px] font-bold text-primary uppercase hover:underline tracking-wider">
          Export CSV
        </button>
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
            icon="person_search"
            title="No leads"
            description="No leads to display"
            className="py-8"
          />
        )}

        {!isLoading && !error && data && data.items.length > 0 && (
          <table className="w-full text-left border-collapse">
            <thead className="sticky top-0 bg-surface-container-high shadow-sm">
              <tr className="text-[9px] font-bold uppercase text-outline tracking-wider">
                <th className="px-4 py-2">Lead Type</th>
                <th className="px-4 py-2">Jurisdiction</th>
                <th className="px-4 py-2">Conf.</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">Updated</th>
              </tr>
            </thead>
            <tbody className="text-[11px] divide-y divide-outline-variant/5">
              {data.items.map((lead, idx) => (
                <tr
                  key={lead.id}
                  className={cn(
                    'hover:bg-surface-container-high transition-colors',
                    idx % 2 === 0 ? 'bg-surface-container-lowest' : ''
                  )}
                >
                  <td className="px-4 py-3 font-medium text-on-surface">
                    {lead.lead_type.toUpperCase()}
                  </td>
                  <td className="px-4 py-3 text-outline">
                    {lead.jurisdiction ?? '—'}
                  </td>
                  <td className="px-4 py-3">
                    <ConfidenceBar confidence={lead.confidence} />
                  </td>
                  <td className="px-4 py-3">
                    <StatusText status={lead.status} />
                  </td>
                  <td className="px-4 py-3 text-outline whitespace-nowrap">
                    {formatRelativeTime(lead.last_updated_at)}
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
