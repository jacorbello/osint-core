import { cn } from '@/lib/utils/cn';
import { formatScore } from '@/lib/utils/format';

interface ScorePillProps {
  score: number;
  className?: string;
}

export function ScorePill({ score, className }: ScorePillProps) {
  const getScoreColor = (value: number): string => {
    if (value >= 0.8) return 'bg-error text-on-error';
    if (value >= 0.6) return 'bg-tertiary-container text-on-tertiary-container';
    if (value >= 0.4) return 'bg-secondary-container text-on-secondary-container';
    return 'bg-primary-container text-on-primary-container';
  };

  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-0.5',
        'text-xs font-label font-medium tabular-nums',
        getScoreColor(score),
        className
      )}
    >
      {formatScore(score)}
    </span>
  );
}
