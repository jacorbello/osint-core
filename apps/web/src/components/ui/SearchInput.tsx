import { forwardRef, InputHTMLAttributes } from 'react';
import { cn } from '@/lib/utils/cn';

export type SearchInputProps = InputHTMLAttributes<HTMLInputElement>;

export const SearchInput = forwardRef<HTMLInputElement, SearchInputProps>(
  ({ className, ...props }, ref) => {
    return (
      <div className="relative">
        <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant">
          search
        </span>
        <input
          ref={ref}
          type="search"
          className={cn(
            'flex h-10 w-full rounded bg-surface-container-high border border-outline-variant pl-10 pr-3 py-2',
            'text-sm text-on-surface placeholder:text-on-surface-variant',
            'focus:outline-none focus:ring-2 focus:ring-primary-container focus:border-transparent',
            'disabled:cursor-not-allowed disabled:opacity-50',
            className
          )}
          {...props}
        />
      </div>
    );
  }
);

SearchInput.displayName = 'SearchInput';
