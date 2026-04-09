import { useState, useMemo } from 'react';
import {
  useReactTable,
  getCoreRowModel,
  getSortedRowModel,
  getPaginationRowModel,
  flexRender,
  createColumnHelper,
  type SortingState,
  type PaginationState,
} from '@tanstack/react-table';
import { useAlertsQuery } from '@/features/alerts/api/alertsQueries';
import { AlertsFilters } from './AlertsFilters';
import { getSeverityColor, getSeverityBorderColor } from '@/lib/utils/severity';
import { formatRelativeTime } from '@/lib/utils/format';
import { cn } from '@/lib/utils/cn';
import { SkeletonTable } from '@/components/feedback/SkeletonTable';
import { ErrorBanner } from '@/components/feedback/ErrorBanner';
import { EmptyState } from '@/components/feedback/EmptyState';
import type { AlertResponse } from '@/types/api/alert';
import type { SeverityEnum, StatusEnum, ProblemDetails } from '@/types/api/common';

const PAGE_SIZE_OPTIONS = [10, 25, 50] as const;

const columnHelper = createColumnHelper<AlertResponse>();

function StatusBadge({ status }: { status: StatusEnum }) {
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

const columns = [
  columnHelper.accessor('severity', {
    header: 'Severity',
    cell: (info) => {
      const severity = info.getValue() as SeverityEnum;
      return (
        <div className="flex items-center gap-2">
          <span
            className={cn(
              'px-1.5 py-0.5 rounded text-[9px] font-bold',
              getSeverityColor(severity)
            )}
          >
            {severity.toUpperCase()}
          </span>
        </div>
      );
    },
    sortingFn: (rowA, rowB) => {
      const order: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };
      return (order[rowA.original.severity] ?? 5) - (order[rowB.original.severity] ?? 5);
    },
  }),
  columnHelper.accessor('title', {
    header: 'Title',
    cell: (info) => (
      <span className="font-medium text-on-surface truncate block max-w-[300px]">
        {info.getValue()}
      </span>
    ),
  }),
  columnHelper.accessor('route_name', {
    header: 'Watch Source',
    cell: (info) => (
      <span className="text-on-surface-variant">{info.getValue() ?? '--'}</span>
    ),
  }),
  columnHelper.accessor('status', {
    header: 'Status',
    cell: (info) => <StatusBadge status={info.getValue()} />,
  }),
  columnHelper.accessor('occurrences', {
    header: 'Occurrences',
    cell: (info) => (
      <span className="font-mono text-on-surface-variant">
        {info.getValue().toLocaleString()}
      </span>
    ),
    meta: { align: 'right' },
  }),
  columnHelper.accessor('last_fired_at', {
    header: 'Last Fired',
    cell: (info) => (
      <span className="text-outline whitespace-nowrap">
        {formatRelativeTime(info.getValue())}
      </span>
    ),
  }),
];

export function AlertsPage() {
  const [selectedSeverities, setSelectedSeverities] = useState<SeverityEnum[]>([]);
  const [selectedStatus, setSelectedStatus] = useState<StatusEnum | undefined>(undefined);
  const [sorting, setSorting] = useState<SortingState>([]);
  const [pagination, setPagination] = useState<PaginationState>({
    pageIndex: 0,
    pageSize: 10,
  });

  const queryParams = useMemo(
    () => ({
      severity: selectedSeverities.length === 1 ? selectedSeverities[0] : undefined,
      status: selectedStatus,
      limit: pagination.pageSize,
      offset: pagination.pageIndex * pagination.pageSize,
    }),
    [selectedSeverities, selectedStatus, pagination]
  );

  const { data, isLoading, error } = useAlertsQuery(queryParams);

  const filteredItems = useMemo(() => {
    if (!data?.items) return [];
    if (selectedSeverities.length <= 1) return data.items;
    return data.items.filter((item) =>
      selectedSeverities.includes(item.severity as SeverityEnum)
    );
  }, [data?.items, selectedSeverities]);

  const table = useReactTable({
    data: filteredItems,
    columns,
    state: { sorting, pagination },
    onSortingChange: setSorting,
    onPaginationChange: setPagination,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    manualPagination: true,
    pageCount: data?.page ? Math.ceil(data.page.total / pagination.pageSize) : -1,
  });

  return (
    <div className="flex flex-col h-full p-8 gap-6" data-testid="alerts-page">
      <div>
        <h1 className="text-2xl font-headline font-semibold text-on-surface flex items-center gap-2">
          <span
            className="material-symbols-outlined text-error"
            style={{ fontVariationSettings: "'FILL' 1" }}
          >
            warning
          </span>
          Alerts
        </h1>
        <p className="mt-1 text-sm text-on-surface-variant">
          Review and triage intelligence alerts.
        </p>
      </div>

      <AlertsFilters
        selectedSeverities={selectedSeverities}
        onSeveritiesChange={(severities) => {
          setSelectedSeverities(severities);
          setPagination((prev) => ({ ...prev, pageIndex: 0 }));
        }}
        selectedStatus={selectedStatus}
        onStatusChange={(status) => {
          setSelectedStatus(status);
          setPagination((prev) => ({ ...prev, pageIndex: 0 }));
        }}
      />

      <div className="bg-surface-container-low rounded-lg border border-outline-variant/10 overflow-hidden flex flex-col flex-1">
        {isLoading && (
          <div className="p-6">
            <SkeletonTable rows={pagination.pageSize > 10 ? 10 : pagination.pageSize} columns={6} />
          </div>
        )}

        {!isLoading && error && (
          <ErrorBanner error={error as unknown as ProblemDetails} className="m-4" />
        )}

        {!isLoading && !error && filteredItems.length === 0 && (
          <EmptyState
            icon="notifications_off"
            title="No alerts"
            description={
              selectedSeverities.length > 0 || selectedStatus
                ? 'No alerts match the current filters. Try adjusting your filters.'
                : 'No alerts to display.'
            }
            className="py-16"
          />
        )}

        {!isLoading && !error && filteredItems.length > 0 && (
          <>
            <div className="flex-1 overflow-auto">
              <table className="w-full text-left border-collapse" data-testid="alerts-table">
                <thead className="sticky top-0 bg-surface-container-high shadow-sm">
                  {table.getHeaderGroups().map((headerGroup) => (
                    <tr
                      key={headerGroup.id}
                      className="text-[9px] font-bold uppercase text-outline tracking-wider"
                    >
                      {headerGroup.headers.map((header) => {
                        const meta = header.column.columnDef.meta as
                          | { align?: string }
                          | undefined;
                        return (
                          <th
                            key={header.id}
                            className={cn(
                              'px-4 py-2 select-none',
                              header.column.getCanSort() && 'cursor-pointer hover:text-on-surface',
                              meta?.align === 'right' && 'text-right'
                            )}
                            onClick={header.column.getToggleSortingHandler()}
                            data-testid={`sort-header-${header.column.id}`}
                          >
                            <span className="inline-flex items-center gap-1">
                              {flexRender(
                                header.column.columnDef.header,
                                header.getContext()
                              )}
                              {{
                                asc: (
                                  <span className="material-symbols-outlined text-[12px]">
                                    arrow_upward
                                  </span>
                                ),
                                desc: (
                                  <span className="material-symbols-outlined text-[12px]">
                                    arrow_downward
                                  </span>
                                ),
                              }[header.column.getIsSorted() as string] ?? null}
                            </span>
                          </th>
                        );
                      })}
                    </tr>
                  ))}
                </thead>
                <tbody className="text-[11px] divide-y divide-outline-variant/5">
                  {table.getRowModel().rows.map((row, idx) => {
                    const severity = row.original.severity as SeverityEnum;
                    return (
                      <tr
                        key={row.id}
                        className={cn(
                          'hover:bg-surface-container-high transition-colors relative',
                          idx % 2 === 0 ? 'bg-surface-container-lowest' : ''
                        )}
                        data-testid="alert-row"
                      >
                        {row.getVisibleCells().map((cell, cellIdx) => {
                          const meta = cell.column.columnDef.meta as
                            | { align?: string }
                            | undefined;
                          return (
                            <td
                              key={cell.id}
                              className={cn(
                                'px-4 py-3',
                                cellIdx === 0 &&
                                  `border-l-[3px] ${getSeverityBorderColor(severity)}`,
                                meta?.align === 'right' && 'text-right'
                              )}
                            >
                              {flexRender(cell.column.columnDef.cell, cell.getContext())}
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            <div
              className="flex items-center justify-between px-4 py-3 border-t border-outline-variant/10 bg-surface-container-high flex-shrink-0"
              data-testid="pagination-controls"
            >
              <div className="flex items-center gap-2 text-xs text-on-surface-variant">
                <span>Rows per page:</span>
                <select
                  value={pagination.pageSize}
                  onChange={(e) =>
                    setPagination({ pageIndex: 0, pageSize: Number(e.target.value) })
                  }
                  className="bg-surface-container rounded px-2 py-1 text-xs text-on-surface border border-outline-variant/20"
                  data-testid="page-size-select"
                >
                  {PAGE_SIZE_OPTIONS.map((size) => (
                    <option key={size} value={size}>
                      {size}
                    </option>
                  ))}
                </select>
              </div>

              <div className="flex items-center gap-3 text-xs text-on-surface-variant">
                <span data-testid="page-info">
                  Page {pagination.pageIndex + 1} of{' '}
                  {Math.max(1, table.getPageCount())}
                </span>
                <div className="flex gap-1">
                  <button
                    onClick={() => table.previousPage()}
                    disabled={!table.getCanPreviousPage()}
                    className="p-1 rounded hover:bg-surface-container disabled:opacity-30 disabled:cursor-not-allowed"
                    data-testid="prev-page-btn"
                  >
                    <span className="material-symbols-outlined text-base">chevron_left</span>
                  </button>
                  <button
                    onClick={() => table.nextPage()}
                    disabled={!table.getCanNextPage()}
                    className="p-1 rounded hover:bg-surface-container disabled:opacity-30 disabled:cursor-not-allowed"
                    data-testid="next-page-btn"
                  >
                    <span className="material-symbols-outlined text-base">chevron_right</span>
                  </button>
                </div>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
