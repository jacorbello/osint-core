import { cn } from '@/lib/utils/cn';
import { formatNumber } from '@/lib/utils/format';

interface CountBadgeProps {
  count: number;
  label?: string;
  className?: string;
}

export function CountBadge({ count, label, className }: CountBadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-2.5 py-0.5',
        'text-xs font-label font-medium',
        'bg-surface-container-high text-on-surface',
        className
      )}
    >
      {label && <span className="text-on-surface-variant">{label}</span>}
      <span>{formatNumber(count)}</span>
    </span>
  );
}
