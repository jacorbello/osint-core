import { screen } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { AppShell } from '@/components/layout/AppShell';
import { renderWithRouterAndProviders } from '@/test/renderWithProviders';
import { vi } from 'vitest';

// Mock useSSEFeed used by TopBar
vi.mock('@/features/stream/hooks/useSSEFeed', () => ({
  useSSEFeed: () => ({ events: [], connected: true }),
}));

describe('AppShell', () => {
  it('renders sidebar, top bar, and route content', () => {
    renderWithRouterAndProviders(
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route path="dashboard" element={<h1>Dashboard test page</h1>} />
        </Route>
      </Routes>,
      { router: { initialEntries: ['/dashboard'] } }
    );

    // TopBar renders dynamic page title instead of branding
    expect(screen.getByRole('heading', { name: 'Overview' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Dashboard test page' })).toBeTruthy();
    expect(screen.getByRole('navigation')).toBeTruthy();
  });

  it('renders with CSS Grid layout', () => {
    const { container } = renderWithRouterAndProviders(
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route index element={<div>Home</div>} />
        </Route>
      </Routes>,
      { router: { initialEntries: ['/'] } }
    );

    const grid = container.firstChild as HTMLElement;
    expect(grid.style.gridTemplateColumns).toBe('200px 1fr');
    expect(grid.style.gridTemplateRows).toBe('44px 1fr');
  });

  it('no hardcoded ml-[72px] offset', () => {
    const { container } = renderWithRouterAndProviders(
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route index element={<div>Home</div>} />
        </Route>
      </Routes>,
      { router: { initialEntries: ['/'] } }
    );

    expect(container.innerHTML).not.toContain('ml-[72px]');
  });

  it('renders sidebar with intelligence cycle navigation', () => {
    renderWithRouterAndProviders(
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route path="dashboard" element={<div>content</div>} />
        </Route>
      </Routes>,
      { router: { initialEntries: ['/dashboard'] } }
    );

    expect(screen.getByText('OSINT Core')).toBeTruthy();
    expect(screen.getByText('COLLECT')).toBeTruthy();
    expect(screen.getByText('ANALYZE')).toBeTruthy();
    expect(screen.getByText('PRODUCE')).toBeTruthy();
  });
});
