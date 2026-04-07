import { cn } from '@/lib/utils/cn';
import { formatNumber } from '@/lib/utils/format';

interface SummaryMetricCardProps {
  label: string;
  counts: Record<string, number>;
  variant?: 'alerts' | 'leads' | 'jobs' | 'events';
  className?: string;
}

function getStatusBadgeColor(status: string, variant?: string): string {
  if (variant === 'alerts') {
    if (status === 'open') return 'bg-error-container text-on-error-container';
    if (status === 'escalated') return 'bg-tertiary-container/20 text-tertiary-container';
    return 'bg-surface-container-highest text-on-surface-variant';
  }
  
  if (variant === 'leads') {
    if (status === 'new') return 'bg-primary-container/20 text-primary-container';
    return 'bg-surface-container-highest text-on-surface-variant';
  }
  
  if (variant === 'jobs') {
    if (status === 'running') return 'bg-secondary-container/30 text-on-secondary-container';
    if (status === 'failed') return 'bg-error-container/20 text-error';
    return 'bg-surface-container-highest text-on-surface-variant';
  }
  
  return 'bg-surface-container-highest text-on-surface-variant';
}

export function SummaryMetricCard({ label, counts, variant, className }: SummaryMetricCardProps) {
  const entries = Object.entries(counts).filter(([, count]) => count > 0);

  return (
    <div
      className={cn('flex items-center gap-2 border-r border-outline-variant/20 pr-6', className)}
      data-variant={variant}
    >
      <span className="text-[10px] font-bold text-outline uppercase tracking-wider mr-2">
        {label}
      </span>
      <div className="flex gap-1.5">
        {entries.map(([status, count]) => {
          const isHighlighted = 
            (variant === 'alerts' && status === 'open') ||
            (variant === 'leads' && status === 'new') ||
            (variant === 'jobs' && (status === 'running' || status === 'failed'));
          
          return (
            <span
              key={status}
              className={cn(
                'px-2 py-0.5 rounded-full text-[10px]',
                isHighlighted ? 'font-bold' : 'font-medium',
                getStatusBadgeColor(status, variant)
              )}
            >
              {formatNumber(count)} {status.toUpperCase()}
            </span>
          );
        })}
      </div>
    </div>
  );
}
