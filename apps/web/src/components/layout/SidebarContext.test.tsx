import { renderHook, act } from '@testing-library/react';
import { SidebarProvider, useSidebar } from './SidebarContext';
import type { ReactNode } from 'react';

function wrapper({ children }: { children: ReactNode }) {
  return <SidebarProvider>{children}</SidebarProvider>;
}

beforeEach(() => {
  localStorage.clear();
});

describe('SidebarContext', () => {
  it('defaults to expanded (collapsed = false)', () => {
    const { result } = renderHook(() => useSidebar(), { wrapper });
    expect(result.current.collapsed).toBe(false);
  });

  it('toggleCollapsed flips state', () => {
    const { result } = renderHook(() => useSidebar(), { wrapper });
    act(() => result.current.toggleCollapsed());
    expect(result.current.collapsed).toBe(true);
    act(() => result.current.toggleCollapsed());
    expect(result.current.collapsed).toBe(false);
  });

  it('persists collapsed state to localStorage', () => {
    const { result } = renderHook(() => useSidebar(), { wrapper });
    act(() => result.current.toggleCollapsed());
    expect(localStorage.getItem('osint-sidebar-collapsed')).toBe('true');
    act(() => result.current.toggleCollapsed());
    expect(localStorage.getItem('osint-sidebar-collapsed')).toBe('false');
  });

  it('reads initial state from localStorage', () => {
    localStorage.setItem('osint-sidebar-collapsed', 'true');
    const { result } = renderHook(() => useSidebar(), { wrapper });
    expect(result.current.collapsed).toBe(true);
  });

  it('throws when used outside SidebarProvider', () => {
    expect(() => {
      renderHook(() => useSidebar());
    }).toThrow('useSidebar must be used within a SidebarProvider');
  });
});
