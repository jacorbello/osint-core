import { screen, waitFor } from '@testing-library/react';
import { renderWithRouterAndProviders } from '@/test/renderWithProviders';
import { OverviewPage } from './OverviewPage';
import * as dashboardApi from '../api/dashboardApi';
import type { DashboardSummaryResponse } from '@/types/api/ui';

vi.mock('../api/dashboardApi');
vi.mock('react-leaflet', () => ({
  MapContainer: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="leaflet-map">{children}</div>
  ),
  TileLayer: () => <div />,
  CircleMarker: () => <div />,
  useMapEvents: () => null,
}));
vi.mock('leaflet/dist/leaflet.css', () => ({}));
vi.mock('@/features/alerts/api/alertsQueries', () => ({
  useAlertsQuery: () => ({ data: undefined, isLoading: false, error: null }),
}));
vi.mock('@/features/leads/api/leadsQueries', () => ({
  useLeadsQuery: () => ({ data: undefined, isLoading: false, error: null }),
}));
vi.mock('@/features/stream/hooks/useSSEFeed', () => ({
  useSSEFeed: () => ({ events: [], connected: false }),
}));

describe('OverviewPage', () => {
  const mockSummary: DashboardSummaryResponse = {
    alerts: { open: 12, acked: 4 },
    leads: { new: 8, active: 15 },
    jobs: { running: 2, completed: 45 },
    watches: { active: 10 },
    events: { last_24h_count: 1234 },
    updated_at: '2026-04-07T12:00:00Z',
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders all 4 StatusCards with data from dashboard summary', async () => {
    vi.spyOn(dashboardApi, 'getDashboardSummary').mockResolvedValue(mockSummary);

    renderWithRouterAndProviders(<OverviewPage />);

    await waitFor(() => {
      expect(screen.getByTestId('status-cards-row')).toBeInTheDocument();
    });

    const cards = screen.getAllByTestId('status-card-count');
    expect(cards).toHaveLength(4);

    expect(screen.getByText('Open Alerts')).toBeInTheDocument();
    expect(screen.getByText('Active Leads')).toBeInTheDocument();
    expect(screen.getByText('Active Watches')).toBeInTheDocument();
    expect(screen.getByText('Jobs')).toBeInTheDocument();
  });

  it('renders PriorityAlertsList in left column', async () => {
    vi.spyOn(dashboardApi, 'getDashboardSummary').mockResolvedValue(mockSummary);

    renderWithRouterAndProviders(<OverviewPage />);

    await waitFor(() => {
      expect(screen.getByText('Priority Alerts')).toBeInTheDocument();
    });
  });

  it('renders ActivityFeed in right rail', async () => {
    vi.spyOn(dashboardApi, 'getDashboardSummary').mockResolvedValue(mockSummary);

    renderWithRouterAndProviders(<OverviewPage />);

    await waitFor(() => {
      expect(screen.getByTestId('activity-feed')).toBeInTheDocument();
    });
  });

  it('renders MiniMap in left column', async () => {
    vi.spyOn(dashboardApi, 'getDashboardSummary').mockResolvedValue(mockSummary);

    renderWithRouterAndProviders(<OverviewPage />);

    await waitFor(() => {
      expect(screen.getByTestId('minimap-collapsed')).toBeInTheDocument();
    });
  });

  it('shows skeleton loading states for all sections', () => {
    vi.spyOn(dashboardApi, 'getDashboardSummary').mockImplementation(
      () => new Promise(() => {})
    );

    renderWithRouterAndProviders(<OverviewPage />);

    expect(screen.getByTestId('status-cards-skeleton')).toBeInTheDocument();
    expect(document.querySelector('.animate-pulse')).toBeInTheDocument();
  });

  it('shows error banner on API failure', async () => {
    vi.spyOn(dashboardApi, 'getDashboardSummary').mockRejectedValue({
      type: 'about:blank',
      title: 'Internal Server Error',
      status: 500,
      detail: 'Database connection failed',
    });

    renderWithRouterAndProviders(<OverviewPage />);

    await waitFor(() => {
      expect(screen.getByText(/Database connection failed/)).toBeInTheDocument();
    });
  });

  it('renders LeadsTableWidget below alerts', async () => {
    vi.spyOn(dashboardApi, 'getDashboardSummary').mockResolvedValue(mockSummary);

    renderWithRouterAndProviders(<OverviewPage />);

    await waitFor(() => {
      expect(screen.getByText('Recent Leads')).toBeInTheDocument();
    });
  });
});
