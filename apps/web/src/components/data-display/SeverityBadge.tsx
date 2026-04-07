import { SeverityEnum } from '@/types/api/common';
import { getSeverityColor } from '@/lib/utils/severity';
import { cn } from '@/lib/utils/cn';

interface SeverityBadgeProps {
  severity: SeverityEnum;
  className?: string;
}

export function SeverityBadge({ severity, className }: SeverityBadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-label font-medium uppercase',
        getSeverityColor(severity),
        className
      )}
    >
      {severity}
    </span>
  );
}
