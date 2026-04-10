import { useLocation } from 'react-router-dom';
import { cn } from '@/lib/utils/cn';
import { useSSEFeed } from '@/features/stream/hooks/useSSEFeed';

const ROUTE_TITLES: Record<string, string> = {
  '/': 'Overview',
  '/dashboard': 'Overview',
  '/watches': 'Watches',
  '/sources': 'Sources',
  '/alerts': 'Alerts',
  '/investigations': 'Investigations',
  '/entities': 'Entities',
  '/leads': 'Leads',
  '/reports': 'Reports',
  '/exports': 'Exports',
  '/map': 'Intelligence Map',
  '/settings': 'Settings',
};

function getPageTitle(pathname: string): string {
  if (ROUTE_TITLES[pathname]) return ROUTE_TITLES[pathname];

  const segments = pathname.split('/').filter(Boolean);
  if (segments.length > 0) {
    const parent = `/${segments[0]}`;
    if (ROUTE_TITLES[parent]) return ROUTE_TITLES[parent];
  }

  return 'Overview';
}

export function TopBar() {
  const location = useLocation();
  const { connected } = useSSEFeed('/api/stream');
  const pageTitle = getPageTitle(location.pathname);

  return (
    <header
      className="h-[44px] bg-surface border-b border-outline-variant flex items-center justify-between px-6"
    >
      {/* Page title */}
      <h1 className="text-sm font-headline font-semibold text-on-surface">
        {pageTitle}
      </h1>

      <div className="flex items-center gap-4">
        {/* Cmd+K search trigger */}
        <button
          type="button"
          aria-label="Open search"
          onClick={() => {
            document.dispatchEvent(
              new KeyboardEvent('keydown', { key: 'k', metaKey: true })
            );
          }}
          className="flex items-center gap-2 h-7 px-3 rounded bg-surface-container text-text-muted text-xs font-body border border-outline-variant hover:border-outline transition-colors cursor-pointer"
        >
          <span className="text-text-tertiary">{'\u2318'}K</span>
          <span>Search...</span>
        </button>

        {/* Connection status */}
        <div className="flex items-center gap-1.5 text-xs font-body" data-testid="connection-status">
          <span
            className={cn(
              'w-2 h-2 rounded-full',
              connected ? 'bg-success' : 'bg-error'
            )}
          />
          <span className={cn(
            connected ? 'text-on-surface-variant' : 'text-error'
          )}>
            {connected ? 'Connected' : 'Disconnected'}
          </span>
        </div>

        {/* Notification bell */}
        <button
          type="button"
          aria-label="Notifications"
          className="relative text-on-surface-variant hover:text-on-surface transition-colors cursor-pointer"
        >
          <span className="material-symbols-outlined text-[20px]">notifications</span>
          <span
            className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-error"
            data-testid="notification-indicator"
          />
        </button>
      </div>
    </header>
  );
}
