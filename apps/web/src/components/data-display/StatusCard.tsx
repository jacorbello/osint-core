import { cn } from '@/lib/utils/cn';

export interface BreakdownItem {
  label: string;
  count: number;
  color: string;
}

interface StatusCardProps {
  label: string;
  count: number;
  breakdowns: BreakdownItem[];
  className?: string;
}

function hasCritical(breakdowns: BreakdownItem[]): boolean {
  return breakdowns.some((b) => b.color === 'critical');
}

const colorMap: Record<string, string> = {
  critical: 'text-critical',
  warning: 'text-warning',
  primary: 'text-primary',
  success: 'text-success',
  'text-secondary': 'text-text-secondary',
  'text-tertiary': 'text-text-tertiary',
  'text-muted': 'text-text-muted',
};

export function StatusCard({ label, count, breakdowns, className }: StatusCardProps) {
  const countColor = hasCritical(breakdowns) ? 'text-critical' : 'text-text-primary';

  return (
    <div
      className={cn(
        'bg-surface-container-high border border-outline-variant rounded-md px-3 py-2.5',
        className
      )}
    >
      <p className="text-xs text-text-secondary font-label">{label}</p>
      <p
        data-testid="status-card-count"
        className={cn('text-lg font-semibold', countColor)}
      >
        {count}
      </p>
      {breakdowns.length > 0 && (
        <p data-testid="status-card-breakdowns" className="text-[9px] text-text-secondary leading-tight">
          {breakdowns.map((b, i) => (
            <span key={b.label}>
              {i > 0 && ', '}
              <span className={colorMap[b.color] ?? 'text-text-secondary'}>
                {b.count} {b.label}
              </span>
            </span>
          ))}
        </p>
      )}
    </div>
  );
}
