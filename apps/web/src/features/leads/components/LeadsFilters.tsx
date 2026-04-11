import type { LeadStatusEnum, LeadTypeEnum } from '@/types/api/lead';

export interface LeadsFilterState {
  lead_type: LeadTypeEnum | '';
  status: LeadStatusEnum | '';
  confidence_min: number;
  confidence_max: number;
}

const LEAD_TYPES: { value: LeadTypeEnum | ''; label: string }[] = [
  { value: '', label: 'All types' },
  { value: 'incident', label: 'Incident' },
  { value: 'policy', label: 'Policy' },
];

const LEAD_STATUSES: { value: LeadStatusEnum | ''; label: string }[] = [
  { value: '', label: 'All statuses' },
  { value: 'new', label: 'New' },
  { value: 'reviewing', label: 'Reviewing' },
  { value: 'qualified', label: 'Qualified' },
  { value: 'declined', label: 'Declined' },
];

interface LeadsFiltersProps {
  filters: LeadsFilterState;
  onChange: (filters: LeadsFilterState) => void;
}

export function LeadsFilters({ filters, onChange }: LeadsFiltersProps) {
  return (
    <div className="flex flex-wrap items-end gap-4">
      {/* Type filter */}
      <div className="flex flex-col gap-1">
        <label
          htmlFor="lead-type-filter"
          className="text-[11px] font-medium uppercase tracking-wider text-on-surface-variant"
        >
          Type
        </label>
        <select
          id="lead-type-filter"
          value={filters.lead_type}
          onChange={(e) =>
            onChange({ ...filters, lead_type: e.target.value as LeadTypeEnum | '' })
          }
          className="rounded border border-outline-variant/20 bg-surface-container-low px-3 py-1.5 text-sm text-on-surface focus:border-primary focus:outline-none"
        >
          {LEAD_TYPES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
      </div>

      {/* Status filter */}
      <div className="flex flex-col gap-1">
        <label
          htmlFor="lead-status-filter"
          className="text-[11px] font-medium uppercase tracking-wider text-on-surface-variant"
        >
          Status
        </label>
        <select
          id="lead-status-filter"
          value={filters.status}
          onChange={(e) =>
            onChange({ ...filters, status: e.target.value as LeadStatusEnum | '' })
          }
          className="rounded border border-outline-variant/20 bg-surface-container-low px-3 py-1.5 text-sm text-on-surface focus:border-primary focus:outline-none"
        >
          {LEAD_STATUSES.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
      </div>

      {/* Confidence range */}
      <div className="flex flex-col gap-1">
        <label className="text-[11px] font-medium uppercase tracking-wider text-on-surface-variant">
          Confidence
        </label>
        <div className="flex items-center gap-2">
          <input
            type="number"
            aria-label="Minimum confidence"
            min={0}
            max={100}
            value={filters.confidence_min}
            onChange={(e) =>
              onChange({
                ...filters,
                confidence_min: Math.max(0, Math.min(100, Number(e.target.value))),
              })
            }
            className="w-16 rounded border border-outline-variant/20 bg-surface-container-low px-2 py-1.5 text-sm text-on-surface focus:border-primary focus:outline-none"
          />
          <span className="text-xs text-on-surface-variant">to</span>
          <input
            type="number"
            aria-label="Maximum confidence"
            min={0}
            max={100}
            value={filters.confidence_max}
            onChange={(e) =>
              onChange({
                ...filters,
                confidence_max: Math.max(0, Math.min(100, Number(e.target.value))),
              })
            }
            className="w-16 rounded border border-outline-variant/20 bg-surface-container-low px-2 py-1.5 text-sm text-on-surface focus:border-primary focus:outline-none"
          />
          <span className="text-xs text-on-surface-variant">%</span>
        </div>
      </div>

      {/* Reset */}
      {(filters.lead_type || filters.status || filters.confidence_min > 0 || filters.confidence_max < 100) && (
        <button
          type="button"
          onClick={() => onChange({ lead_type: '', status: '', confidence_min: 0, confidence_max: 100 })}
          className="rounded px-3 py-1.5 text-xs font-medium text-primary hover:bg-primary/10 transition-colors"
        >
          Reset filters
        </button>
      )}
    </div>
  );
}
