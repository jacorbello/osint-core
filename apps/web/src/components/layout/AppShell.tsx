import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { TopBar } from './TopBar';

function getInitialCollapsed(): boolean {
  try {
    return localStorage.getItem('osint-sidebar-collapsed') === 'true';
  } catch {
    return false;
  }
}

export function AppShell() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(getInitialCollapsed);

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <Sidebar onCollapseChange={setSidebarCollapsed} />
      <div
        className="flex flex-col flex-1 transition-all duration-200"
        style={{ marginLeft: sidebarCollapsed ? 48 : 200 }}
      >
        <TopBar sidebarWidth={sidebarCollapsed ? 48 : 200} />
        <main className="flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
