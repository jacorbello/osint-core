import { Outlet } from 'react-router-dom';
import { SidebarProvider, useSidebar } from './SidebarContext';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';

function AppShellInner() {
  const { collapsed } = useSidebar();

  return (
    <div
      className="grid h-screen overflow-hidden bg-background transition-[grid-template-columns] duration-200 ease-in-out"
      style={{
        gridTemplateColumns: `${collapsed ? '48px' : '200px'} 1fr`,
        gridTemplateRows: '44px 1fr',
      }}
    >
      <div className="row-span-2">
        <Sidebar />
      </div>
      <TopBar />
      <main className="overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}

export function AppShell() {
  return (
    <SidebarProvider>
      <AppShellInner />
    </SidebarProvider>
  );
}
