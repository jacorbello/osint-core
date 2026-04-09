import { Link, useLocation } from 'react-router-dom';
import { cn } from '@/lib/utils/cn';
import { useSidebar } from './SidebarContext';

interface NavItem {
  path: string;
  icon: string;
  label: string;
  badge?: string;
}

interface NavSection {
  header: string;
  items: NavItem[];
}

const sections: NavSection[] = [
  {
    header: 'COLLECT',
    items: [
      { path: '/watches', icon: 'visibility', label: 'Watches', badge: 'watches' },
      { path: '/sources', icon: 'travel_explore', label: 'Sources' },
      { path: '/alerts', icon: 'notifications_active', label: 'Alerts', badge: 'alerts' },
    ],
  },
  {
    header: 'ANALYZE',
    items: [
      { path: '/investigations', icon: 'search_insights', label: 'Investigations' },
      { path: '/entities', icon: 'hub', label: 'Entities' },
      { path: '/leads', icon: 'trending_up', label: 'Leads', badge: 'leads' },
    ],
  },
  {
    header: 'PRODUCE',
    items: [
      { path: '/reports', icon: 'summarize', label: 'Reports' },
      { path: '/exports', icon: 'download', label: 'Exports' },
    ],
  },
];

export function Sidebar() {
  const { collapsed, toggleCollapsed } = useSidebar();
  const location = useLocation();

  return (
    <aside
      data-testid="sidebar"
      className={cn(
        'h-screen bg-surface flex flex-col font-headline tracking-tight overflow-hidden border-r border-outline-variant'
      )}
    >
      {/* Branding */}
      <div className={cn(
        'flex items-center gap-2 px-3 py-4 border-b border-outline-variant',
        collapsed ? 'justify-center' : ''
      )}>
        <span className="material-symbols-outlined text-primary shrink-0" style={{ fontSize: 24 }}>
          shield
        </span>
        <div className={cn('overflow-hidden whitespace-nowrap transition-all duration-200', collapsed ? 'w-0 opacity-0' : 'w-auto opacity-100')}>
          <div className="text-sm font-bold text-on-surface tracking-wide">OSINT Core</div>
          <div className="text-[10px] text-on-surface-variant leading-tight">Intelligence Platform</div>
        </div>
      </div>

      {/* Overview link */}
      <nav className="flex flex-col flex-1 overflow-y-auto py-2" role="navigation">
        <NavLink
          path="/dashboard"
          icon="dashboard"
          label="Overview"
          isActive={location.pathname === '/' || location.pathname.startsWith('/dashboard')}
          collapsed={collapsed}
        />

        {/* Sections */}
        {sections.map((section) => (
          <div key={section.header} className="mt-3">
            <div
              className={cn(
                'px-3 py-1 text-[10px] font-bold uppercase tracking-widest text-on-surface-variant overflow-hidden whitespace-nowrap transition-all duration-200',
                collapsed ? 'opacity-0 h-0 py-0' : 'opacity-100'
              )}
            >
              {section.header}
            </div>
            {section.items.map((item) => (
              <NavLink
                key={item.path}
                path={item.path}
                icon={item.icon}
                label={item.label}
                badge={item.badge}
                isActive={location.pathname.startsWith(item.path)}
                collapsed={collapsed}
              />
            ))}
          </div>
        ))}
      </nav>

      {/* Bottom section */}
      <div className="mt-auto border-t border-outline-variant py-2">
        <button
          title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          onClick={toggleCollapsed}
          className="flex items-center gap-2 w-full px-3 py-2 text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high transition-colors"
        >
          <span className="material-symbols-outlined shrink-0" style={{ fontSize: 20 }}>
            {collapsed ? 'chevron_right' : 'chevron_left'}
          </span>
          <span className={cn('text-xs overflow-hidden whitespace-nowrap transition-all duration-200', collapsed ? 'w-0 opacity-0' : 'w-auto opacity-100')}>
            Collapse
          </span>
        </button>
        <Link
          to="/settings"
          title="Settings"
          className="flex items-center gap-2 w-full px-3 py-2 text-on-surface-variant hover:text-on-surface hover:bg-surface-container-high transition-colors"
        >
          <span className="material-symbols-outlined shrink-0" style={{ fontSize: 20 }}>
            settings
          </span>
          <span className={cn('text-xs overflow-hidden whitespace-nowrap transition-all duration-200', collapsed ? 'w-0 opacity-0' : 'w-auto opacity-100')}>
            Settings
          </span>
        </Link>
        <div className={cn(
          'flex items-center gap-2 px-3 py-2',
          collapsed ? 'justify-center' : ''
        )}>
          <div className="w-7 h-7 rounded-full overflow-hidden border border-primary/30 bg-surface-container-high flex items-center justify-center shrink-0">
            <span className="material-symbols-outlined text-primary text-sm">person</span>
          </div>
          <span className={cn('text-xs text-on-surface-variant overflow-hidden whitespace-nowrap transition-all duration-200', collapsed ? 'w-0 opacity-0' : 'w-auto opacity-100')}>
            Analyst
          </span>
        </div>
      </div>
    </aside>
  );
}

interface NavLinkProps {
  path: string;
  icon: string;
  label: string;
  badge?: string;
  isActive: boolean;
  collapsed: boolean;
}

function NavLink({ path, icon, label, badge, isActive, collapsed }: NavLinkProps) {
  return (
    <Link
      to={path}
      className={cn(
        'flex items-center gap-2 px-3 py-1.5 transition-colors relative border-l-2',
        isActive
          ? 'text-primary border-primary bg-surface-container-high/50'
          : 'text-on-surface-variant hover:bg-surface-container-high hover:text-on-surface border-transparent'
      )}
    >
      <span
        className="material-symbols-outlined shrink-0"
        style={{ fontSize: 20, fontVariationSettings: isActive ? "'FILL' 1" : "'FILL' 0" }}
      >
        {icon}
      </span>
      <span className={cn('text-xs overflow-hidden whitespace-nowrap transition-all duration-200', collapsed ? 'w-0 opacity-0' : 'w-auto opacity-100')}>
        {label}
      </span>
      {badge && (
        <span
          data-testid={`badge-${badge}`}
          className={cn(
            'text-[10px] font-bold rounded-full min-w-[18px] h-[18px] flex items-center justify-center shrink-0 ml-auto',
            collapsed ? 'absolute top-0 right-0.5 min-w-[14px] h-[14px] text-[8px]' : '',
            badge === 'alerts' ? 'bg-critical/20 text-critical' : 'bg-primary/20 text-primary'
          )}
        >
          0
        </span>
      )}
    </Link>
  );
}
