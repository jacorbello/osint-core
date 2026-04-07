import { cn } from '@/lib/utils/cn';

interface SuccessBannerProps {
  message: string;
  className?: string;
  onDismiss?: () => void;
}

export function SuccessBanner({ message, className, onDismiss }: SuccessBannerProps) {
  return (
    <div
      className={cn(
        'flex items-start gap-3 p-4 rounded-xl border border-primary bg-primary-container/10',
        className
      )}
    >
      <span className="material-symbols-outlined text-primary flex-shrink-0">check_circle</span>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-on-surface">{message}</p>
      </div>
      {onDismiss && (
        <button
          onClick={onDismiss}
          className="flex-shrink-0 text-on-surface-variant hover:text-primary transition-colors"
        >
          <span className="material-symbols-outlined text-sm">close</span>
        </button>
      )}
    </div>
  );
}
