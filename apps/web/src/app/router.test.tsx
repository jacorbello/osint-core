import { render, screen } from '@testing-library/react';
import { createMemoryRouter, Outlet, RouterProvider } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { router } from './router';

vi.mock('@/features/dashboard/components/DashboardPage', () => ({
  DashboardPage: () => <div data-testid="overview-page">OverviewPage</div>,
}));
vi.mock('@/features/watches/components/WatchesPage', () => ({
  WatchesPage: () => <div data-testid="watches-page">WatchesPage</div>,
}));
vi.mock('@/features/alerts/components/AlertsPage', () => ({
  AlertsPage: () => <div data-testid="alerts-page">AlertsPage</div>,
}));
vi.mock('@/features/leads/components/LeadsPage', () => ({
  LeadsPage: () => <div data-testid="leads-page">LeadsPage</div>,
}));
vi.mock('@/features/map/components/IntelligenceMapPage', () => ({
  IntelligenceMapPage: () => <div data-testid="map-page">IntelligenceMapPage</div>,
}));
vi.mock('@/components/layout/AppShell', () => ({
  AppShell: () => <Outlet />,
}));

function renderRoute(path: string) {
  const routes = router.routes;
  const memoryRouter = createMemoryRouter(routes, {
    initialEntries: [path],
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={memoryRouter} />
    </QueryClientProvider>,
  );
}

describe('router', () => {
  it('renders OverviewPage at /', () => {
    renderRoute('/');
    expect(screen.getByTestId('overview-page')).toBeInTheDocument();
  });

  it('renders WatchesPage at /watches', () => {
    renderRoute('/watches');
    expect(screen.getByTestId('watches-page')).toBeInTheDocument();
  });

  it('renders AlertsPage at /alerts', () => {
    renderRoute('/alerts');
    expect(screen.getByTestId('alerts-page')).toBeInTheDocument();
  });

  it('renders LeadsPage at /leads', () => {
    renderRoute('/leads');
    expect(screen.getByTestId('leads-page')).toBeInTheDocument();
  });

  it('renders IntelligenceMapPage at /map', () => {
    renderRoute('/map');
    expect(screen.getByTestId('map-page')).toBeInTheDocument();
  });

  it('renders PlaceholderPage for /sources', () => {
    renderRoute('/sources');
    expect(screen.getByText('Sources')).toBeInTheDocument();
    expect(screen.getByText('Coming soon', { exact: false })).toBeInTheDocument();
  });

  it('renders PlaceholderPage for /investigations/:id', () => {
    renderRoute('/investigations/abc-123');
    expect(screen.getByText('Investigations')).toBeInTheDocument();
  });

  it('renders PlaceholderPage for /entities/:id', () => {
    renderRoute('/entities/entity-456');
    expect(screen.getByText('Entities')).toBeInTheDocument();
  });

  it('renders PlaceholderPage for /reports', () => {
    renderRoute('/reports');
    expect(screen.getByText('Reports')).toBeInTheDocument();
  });

  it('renders PlaceholderPage for /exports', () => {
    renderRoute('/exports');
    expect(screen.getByText('Exports')).toBeInTheDocument();
  });

  it('renders PlaceholderPage for /settings', () => {
    renderRoute('/settings');
    expect(screen.getByText('Settings')).toBeInTheDocument();
  });

  it('does not have /dashboard route', () => {
    renderRoute('/dashboard');
    expect(screen.queryByTestId('overview-page')).not.toBeInTheDocument();
  });

  it('does not have /events route', () => {
    renderRoute('/events');
    expect(screen.queryByText('Events Explorer')).not.toBeInTheDocument();
  });

  it('does not have /plans route', () => {
    renderRoute('/plans');
    expect(screen.queryByText('Plans Workspace')).not.toBeInTheDocument();
  });

  it('does not have /briefs route', () => {
    renderRoute('/briefs');
    expect(screen.queryByText('Briefs Library')).not.toBeInTheDocument();
  });
});
