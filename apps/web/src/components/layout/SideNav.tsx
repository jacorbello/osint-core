import { Link, useLocation } from 'react-router-dom';
import { cn } from '@/lib/utils/cn';

const navItems = [
  { path: '/dashboard', icon: 'dashboard', label: 'Dashboard' },
  { path: '/events', icon: 'event_note', label: 'Events' },
  { path: '/watches', icon: 'visibility', label: 'Watches' },
  { path: '/sensors', icon: 'sensors', label: 'Sensors' },
  { path: '/history', icon: 'history', label: 'History' },
];

export function SideNav() {
  const location = useLocation();

  return (
    <aside className="w-[72px] h-screen fixed left-0 top-0 z-50 bg-surface flex flex-col items-center py-6 font-headline tracking-tight">
      <div className="mb-10 text-primary-container font-bold text-lg tracking-widest" title="OSINT Platform">
        S
      </div>
      
      <nav className="flex flex-col gap-8 flex-1">
        {navItems.map((item) => {
          const isActive = location.pathname.startsWith(item.path);
          return (
            <Link
              key={item.path}
              to={item.path}
              className={cn(
                'flex flex-col items-center transition-colors scale-95 duration-150 py-2 w-[72px]',
                isActive
                  ? 'text-primary-container border-l-2 border-primary-container bg-surface-container-high/50'
                  : 'text-secondary opacity-60 hover:bg-surface-container-high hover:text-primary-container'
              )}
              title={item.label}
            >
              <span 
                className="material-symbols-outlined" 
                style={{ fontVariationSettings: isActive ? "'FILL' 1" : "'FILL' 0" }}
              >
                {item.icon}
              </span>
            </Link>
          );
        })}
      </nav>

      <div className="mt-auto flex flex-col gap-6 items-center">
        <button className="text-primary-container p-2 rounded-full border border-primary-container/20 hover:bg-primary-container/10 transition-all">
          <span className="material-symbols-outlined">add</span>
        </button>
        <button className="text-secondary opacity-60 hover:text-primary-container transition-colors">
          <span className="material-symbols-outlined">settings</span>
        </button>
        <button className="text-secondary opacity-60 hover:text-primary-container transition-colors">
          <span className="material-symbols-outlined">help</span>
        </button>
      </div>
    </aside>
  );
}
