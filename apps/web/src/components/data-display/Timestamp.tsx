import { formatTimestamp, formatRelativeTime } from '@/lib/utils/format';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/Tooltip';

interface TimestampProps {
  date: string | Date;
  relative?: boolean;
  className?: string;
}

export function Timestamp({ date, relative = false, className }: TimestampProps) {
  const formatted = formatTimestamp(date);
  const relativeTime = formatRelativeTime(date);

  if (relative) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <time className={className} dateTime={typeof date === 'string' ? date : date.toISOString()}>
              {relativeTime}
            </time>
          </TooltipTrigger>
          <TooltipContent>{formatted}</TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  return (
    <time className={className} dateTime={typeof date === 'string' ? date : date.toISOString()}>
      {formatted}
    </time>
  );
}
