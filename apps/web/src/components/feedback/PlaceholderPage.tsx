import { cn } from '@/lib/utils/cn';

interface PlaceholderPageProps {
  icon: string;
  title: string;
  description?: string;
  phase?: string;
  className?: string;
}

export function PlaceholderPage({
  icon,
  title,
  description = 'Coming soon',
  phase,
  className,
}: PlaceholderPageProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center h-full px-4 text-center',
        className,
      )}
    >
      <span className="material-symbols-outlined text-7xl text-on-surface-variant mb-6">
        {icon}
      </span>
      <h1 className="text-2xl font-headline font-semibold text-on-surface mb-2">
        {title}
      </h1>
      <p className="text-sm text-on-surface-variant max-w-md">{description}</p>
      {phase && (
        <span className="mt-4 inline-block rounded-full bg-surface-container px-3 py-1 text-xs font-medium uppercase tracking-wider text-on-surface-variant">
          {phase}
        </span>
      )}
    </div>
  );
}
