import { useState, useMemo } from 'react';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
} from '@tanstack/react-table';
import { useLeadsQuery } from '@/features/leads/api/leadsQueries';
import { LeadsFilters, type LeadsFilterState } from './LeadsFilters';
import { SkeletonTable } from '@/components/feedback/SkeletonTable';
import { ErrorBanner } from '@/components/feedback/ErrorBanner';
import { EmptyState } from '@/components/feedback/EmptyState';
import { cn } from '@/lib/utils/cn';
import { formatRelativeTime } from '@/lib/utils/format';
import type { LeadResponse, LeadStatusEnum } from '@/types/api/lead';
import type { ProblemDetails } from '@/types/api/common';

const PAGE_SIZE = 20;

const DEFAULT_FILTERS: LeadsFilterState = {
  lead_type: '',
  status: '',
  confidence_min: 0,
  confidence_max: 100,
};

/* ─── Status badge ─── */

const statusColors: Partial<Record<LeadStatusEnum, string>> = {
  new: 'text-primary',
  reviewing: 'text-secondary',
  qualified: 'text-success',
  contacted: 'text-tertiary-container',
  retained: 'text-on-primary-container',
  declined: 'text-error',
  stale: 'text-on-surface-variant',
};

function StatusBadge({ status }: { status: LeadStatusEnum }) {
  return (
    <span className={cn('text-[11px] font-medium', statusColors[status] ?? 'text-on-surface-variant')}>
      {status.toUpperCase()}
    </span>
  );
}

/* ─── Confidence bar ─── */

function confidenceColor(pct: number): string {
  if (pct >= 70) return 'bg-primary';
  if (pct >= 40) return 'bg-warning';
  return 'bg-text-muted';
}

function ConfidenceBar({ confidence }: { confidence: number | null }) {
  if (confidence === null) {
    return <span className="text-[9px] text-outline">&mdash;</span>;
  }
  const pct = Math.round(confidence * 100);
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 bg-surface-container-high rounded overflow-hidden">
        <div
          className={cn('h-full rounded', confidenceColor(pct))}
          style={{ width: `${pct}%` }}
          data-testid="confidence-fill"
        />
      </div>
      <span className="text-xs text-on-surface-variant tabular-nums">{pct}%</span>
    </div>
  );
}

/* ─── Column definitions ─── */

const columnHelper = createColumnHelper<LeadResponse>();

const columns = [
  columnHelper.accessor('title', {
    header: 'Lead',
    cell: (info) => (
      <span className="font-medium text-on-surface max-w-[280px] truncate block">
        {info.getValue()}
      </span>
    ),
  }),
  columnHelper.accessor('lead_type', {
    header: 'Type',
    cell: (info) => (
      <span className="text-outline text-xs uppercase">{info.getValue()}</span>
    ),
  }),
  columnHelper.accessor('jurisdiction', {
    header: 'Jurisdiction',
    cell: (info) => (
      <span className="text-on-surface-variant text-xs">{info.getValue() ?? '\u2014'}</span>
    ),
  }),
  columnHelper.accessor('confidence', {
    header: 'Confidence',
    cell: (info) => <ConfidenceBar confidence={info.getValue()} />,
    sortingFn: (a, b) => {
      const aVal = a.original.confidence ?? -1;
      const bVal = b.original.confidence ?? -1;
      return aVal - bVal;
    },
  }),
  columnHelper.accessor('status', {
    header: 'Status',
    cell: (info) => <StatusBadge status={info.getValue()} />,
  }),
  columnHelper.accessor('last_updated_at', {
    header: 'Updated',
    cell: (info) => (
      <span className="text-outline text-xs whitespace-nowrap">
        {formatRelativeTime(info.getValue())}
      </span>
    ),
  }),
  columnHelper.display({
    id: 'actions',
    header: '',
    cell: (info) => (
      <div className="flex items-center gap-1">
        <button
          type="button"
          title="Review"
          className="p-1 rounded hover:bg-surface-container-high transition-colors text-on-surface-variant hover:text-on-surface"
        >
          <span className="material-symbols-outlined text-base">visibility</span>
        </button>
        {info.row.original.status !== 'declined' && info.row.original.status !== 'stale' && (
          <button
            type="button"
            title="Dismiss"
            className="p-1 rounded hover:bg-error/10 transition-colors text-on-surface-variant hover:text-error"
          >
            <span className="material-symbols-outlined text-base">close</span>
          </button>
        )}
      </div>
    ),
  }),
];

/* ─── Main page ─── */

export function LeadsPage() {
  const [filters, setFilters] = useState<LeadsFilterState>(DEFAULT_FILTERS);
  const [page, setPage] = useState(0);
  const [sorting, setSorting] = useState<SortingState>([]);

  const queryParams = useMemo(
    () => ({
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
      ...(filters.lead_type ? { lead_type: filters.lead_type } : {}),
      ...(filters.status ? { status: filters.status } : {}),
      ...(filters.confidence_min > 0 ? { confidence_min: filters.confidence_min / 100 } : {}),
      ...(filters.confidence_max < 100 ? { confidence_max: filters.confidence_max / 100 } : {}),
    }),
    [filters, page],
  );

  const { data, isLoading, error } = useLeadsQuery(queryParams);

  const table = useReactTable({
    data: data?.items ?? [],
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  const totalPages = data ? Math.ceil(data.page.total / PAGE_SIZE) : 0;

  function handleFilterChange(next: LeadsFilterState) {
    setFilters(next);
    setPage(0);
  }

  return (
    <div className="flex flex-col h-full p-8 overflow-hidden">
      {/* Header */}
      <div className="flex-shrink-0 mb-6">
        <h1 className="text-2xl font-headline font-semibold text-on-surface">Leads</h1>
        <p className="mt-1 text-sm text-on-surface-variant">
          Track and prioritize analytical leads.
        </p>
      </div>

      {/* Filters */}
      <div className="flex-shrink-0 mb-4">
        <LeadsFilters filters={filters} onChange={handleFilterChange} />
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto bg-surface-container-low rounded-lg border border-outline-variant/10">
        {isLoading && (
          <div className="p-6">
            <SkeletonTable rows={8} columns={6} />
          </div>
        )}

        {!isLoading && error && (
          <ErrorBanner error={error as unknown as ProblemDetails} className="m-4" />
        )}

        {!isLoading && !error && data?.items.length === 0 && (
          <EmptyState
            icon="person_search"
            title="No leads found"
            description="No leads match the current filters. Try adjusting your criteria."
            className="py-16"
          />
        )}

        {!isLoading && !error && data && data.items.length > 0 && (
          <table className="w-full text-left border-collapse">
            <thead className="sticky top-0 bg-surface-container-high shadow-sm">
              {table.getHeaderGroups().map((headerGroup) => (
                <tr key={headerGroup.id} className="text-[10px] font-bold uppercase text-outline tracking-wider">
                  {headerGroup.headers.map((header) => (
                    <th
                      key={header.id}
                      className={cn(
                        'px-4 py-3',
                        header.column.getCanSort() && 'cursor-pointer select-none hover:text-on-surface',
                      )}
                      onClick={header.column.getToggleSortingHandler()}
                    >
                      <div className="flex items-center gap-1">
                        {header.isPlaceholder
                          ? null
                          : flexRender(header.column.columnDef.header, header.getContext())}
                        {header.column.getIsSorted() === 'asc' && (
                          <span className="material-symbols-outlined text-xs">arrow_upward</span>
                        )}
                        {header.column.getIsSorted() === 'desc' && (
                          <span className="material-symbols-outlined text-xs">arrow_downward</span>
                        )}
                      </div>
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody className="text-sm divide-y divide-outline-variant/5">
              {table.getRowModel().rows.map((row, idx) => (
                <tr
                  key={row.id}
                  className={cn(
                    'hover:bg-surface-container-high transition-colors',
                    idx % 2 === 0 ? 'bg-surface-container-lowest' : '',
                  )}
                >
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="px-4 py-3">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      {!isLoading && data && totalPages > 1 && (
        <div className="flex-shrink-0 flex items-center justify-between mt-4 text-sm text-on-surface-variant">
          <span>
            Showing {page * PAGE_SIZE + 1}&ndash;{Math.min((page + 1) * PAGE_SIZE, data.page.total)}{' '}
            of {data.page.total} leads
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={page === 0}
              onClick={() => setPage((p) => p - 1)}
              className="rounded px-3 py-1 text-xs font-medium border border-outline-variant/20 hover:bg-surface-container-high disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              Previous
            </button>
            <span className="text-xs tabular-nums">
              Page {page + 1} of {totalPages}
            </span>
            <button
              type="button"
              disabled={!data.page.has_more}
              onClick={() => setPage((p) => p + 1)}
              className="rounded px-3 py-1 text-xs font-medium border border-outline-variant/20 hover:bg-surface-container-high disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
