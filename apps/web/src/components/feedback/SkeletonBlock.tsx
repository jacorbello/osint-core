import { cn } from '@/lib/utils/cn';

interface SkeletonBlockProps {
  className?: string;
  width?: string;
  height?: string;
}

export function SkeletonBlock({ className, width, height = '1rem' }: SkeletonBlockProps) {
  return (
    <div
      className={cn('animate-pulse rounded bg-surface-container-high', className)}
      style={{ width, height }}
    />
  );
}
