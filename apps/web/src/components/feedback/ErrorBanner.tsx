import { ProblemDetails } from '@/types/api/common';
import { cn } from '@/lib/utils/cn';

interface ErrorBannerProps {
  error: ProblemDetails | Error | string;
  className?: string;
  onDismiss?: () => void;
}

export function ErrorBanner({ error, className, onDismiss }: ErrorBannerProps) {
  const getErrorMessage = (): { code?: string; detail: string } => {
    if (typeof error === 'string') {
      return { detail: error };
    }
    if (error instanceof Error) {
      return { detail: error.message };
    }
    return { code: error.code, detail: error.detail };
  };

  const { code, detail } = getErrorMessage();

  return (
    <div
      className={cn(
        'flex items-start gap-3 p-4 rounded-xl border border-error bg-error-container/10',
        className
      )}
    >
      <span className="material-symbols-outlined text-error flex-shrink-0">error</span>
      <div className="flex-1 min-w-0">
        {code && (
          <p className="text-sm font-label font-medium text-error uppercase mb-1">{code}</p>
        )}
        <p className="text-sm text-on-surface">{detail}</p>
      </div>
      {onDismiss && (
        <button
          onClick={onDismiss}
          className="flex-shrink-0 text-on-surface-variant hover:text-error transition-colors"
        >
          <span className="material-symbols-outlined text-sm">close</span>
        </button>
      )}
    </div>
  );
}
