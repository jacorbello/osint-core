import { ReactNode } from 'react';
import { cn } from '@/lib/utils/cn';

interface KeyValueItem {
  label: string;
  value: ReactNode;
}

interface KeyValueListProps {
  items: KeyValueItem[];
  className?: string;
  columns?: 1 | 2 | 3;
}

export function KeyValueList({ items, className, columns = 2 }: KeyValueListProps) {
  return (
    <dl
      className={cn(
        'grid gap-x-4 gap-y-3',
        {
          'grid-cols-1': columns === 1,
          'grid-cols-2': columns === 2,
          'grid-cols-3': columns === 3,
        },
        className
      )}
    >
      {items.map((item, index) => (
        <div key={index} className="flex flex-col">
          <dt className="text-xs font-label text-on-surface-variant uppercase tracking-wide">
            {item.label}
          </dt>
          <dd className="mt-1 text-sm text-on-surface">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}
