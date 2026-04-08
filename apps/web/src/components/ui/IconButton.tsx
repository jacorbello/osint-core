import { forwardRef, ButtonHTMLAttributes } from 'react';
import { cn } from '@/lib/utils/cn';

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  ({ className, variant = 'ghost', size = 'md', ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(
          'inline-flex items-center justify-center rounded-full transition-colors',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-container',
          'disabled:opacity-50 disabled:pointer-events-none',
          {
            'bg-primary-container text-on-primary-container hover:bg-primary': variant === 'primary',
            'bg-secondary-container text-on-secondary-container hover:bg-secondary': variant === 'secondary',
            'bg-transparent text-on-surface hover:bg-surface-container-high': variant === 'ghost',
          },
          {
            'h-8 w-8': size === 'sm',
            'h-10 w-10': size === 'md',
            'h-12 w-12': size === 'lg',
          },
          className
        )}
        {...props}
      />
    );
  }
);

IconButton.displayName = 'IconButton';
