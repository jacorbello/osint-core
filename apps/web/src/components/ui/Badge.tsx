import { HTMLAttributes } from 'react';
import { cn } from '@/lib/utils/cn';

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: 'default' | 'primary' | 'secondary' | 'tertiary' | 'error';
}

export function Badge({ className, variant = 'default', ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-label font-medium',
        {
          'bg-surface-container-high text-on-surface': variant === 'default',
          'bg-primary-container text-on-primary-container': variant === 'primary',
          'bg-surface-container text-text-secondary': variant === 'secondary',
          'bg-warning-container text-on-warning-container': variant === 'tertiary',
          'bg-error-container text-on-error-container': variant === 'error',
        },
        className
      )}
      {...props}
    />
  );
}
