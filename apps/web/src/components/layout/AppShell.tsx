import { Outlet } from 'react-router-dom';
import { SideNav } from './SideNav';
import { TopBar } from './TopBar';

export function AppShell() {
  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <SideNav />
      <div className="flex flex-col flex-1 ml-[72px]">
        <TopBar />
        <main className="flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
