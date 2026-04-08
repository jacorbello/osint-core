import { cn } from '@/lib/utils/cn';

const tabs = [
  { id: 'global', label: 'Global' },
  { id: 'tactical', label: 'Tactical' },
  { id: 'strategic', label: 'Strategic' },
];

interface TopBarProps {
  sidebarWidth?: number;
}

export function TopBar({ sidebarWidth = 200 }: TopBarProps) {
  const activeTab = 'tactical';

  return (
    <header
      className="fixed top-0 right-0 h-16 z-40 bg-surface/80 backdrop-blur-xl flex justify-between items-center px-8 w-full font-headline text-sm uppercase tracking-wider transition-all duration-200"
      style={{ left: sidebarWidth }}
    >
      <div className="flex items-center gap-8">
        <span className="font-black text-primary-container">SENTINEL NODE</span>
        <div className="flex gap-6">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              className={cn(
                'transition-all',
                activeTab === tab.id
                  ? 'text-primary-container font-bold border-b-2 border-primary-container'
                  : 'text-secondary opacity-70 hover:text-primary-container'
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-6">
        <div className="flex items-center gap-2 px-3 py-1 bg-surface-container-high rounded text-[10px] font-bold text-primary-container animate-pulse">
          <span className="w-2 h-2 rounded-full bg-primary-container"></span>
          STREAM ACTIVE
        </div>
        <div className="flex items-center gap-4 text-secondary">
          <button className="hover:text-primary-container cursor-pointer transition-colors">
            <span className="material-symbols-outlined">notifications</span>
          </button>
          <button className="hover:text-primary-container cursor-pointer transition-colors">
            <span className="material-symbols-outlined">shield</span>
          </button>
          <div className="w-8 h-8 rounded-full overflow-hidden border border-primary-container/30 bg-surface-container-high flex items-center justify-center">
            <span className="material-symbols-outlined text-primary-container text-sm">person</span>
          </div>
        </div>
      </div>
    </header>
  );
}
