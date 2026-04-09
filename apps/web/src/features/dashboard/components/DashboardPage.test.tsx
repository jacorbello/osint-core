import { screen, waitFor } from '@testing-library/react';
import { renderWithRouterAndProviders } from '@/test/renderWithProviders';
import { DashboardPage } from './DashboardPage';
import * as dashboardApi from '../api/dashboardApi';
import type { DashboardSummaryResponse } from '@/types/api/ui';

vi.mock('../api/dashboardApi');
vi.mock('@/features/alerts/api/alertsQueries', () => ({
  useAlertsQuery: () => ({ data: undefined, isLoading: false, error: null }),
}));
vi.mock('@/features/leads/api/leadsQueries', () => ({
  useLeadsQuery: () => ({ data: undefined, isLoading: false, error: null }),
}));
vi.mock('@/features/stream/hooks/useSSEFeed', () => ({
  useSSEFeed: () => ({ events: [], connected: false }),
}));

describe('DashboardPage', () => {
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

  it('fetches dashboard summary on mount', async () => {
    const getDashboardSummarySpy = vi
      .spyOn(dashboardApi, 'getDashboardSummary')
      .mockResolvedValue(mockSummary);

    renderWithRouterAndProviders(<DashboardPage />);

    await waitFor(() => {
      expect(getDashboardSummarySpy).toHaveBeenCalledTimes(1);
    });
  });

  it('shows skeleton during loading', () => {
    vi.spyOn(dashboardApi, 'getDashboardSummary').mockImplementation(
      () => new Promise(() => {})
    );

    renderWithRouterAndProviders(<DashboardPage />);

    expect(document.querySelector('.animate-pulse')).toBeInTheDocument();
  });

  it('shows error banner on failure', async () => {
    vi.spyOn(dashboardApi, 'getDashboardSummary').mockRejectedValue({
      type: 'about:blank',
      title: 'Internal Server Error',
      status: 500,
      detail: 'Database connection failed',
    });

    renderWithRouterAndProviders(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText(/Database connection failed/)).toBeInTheDocument();
    });
  });

  it('renders summary strip with data on success', async () => {
    vi.spyOn(dashboardApi, 'getDashboardSummary').mockResolvedValue(mockSummary);

    renderWithRouterAndProviders(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText('Alerts')).toBeInTheDocument();
      expect(screen.getByText(/12/)).toBeInTheDocument();
      expect(screen.getByText(/OPEN/)).toBeInTheDocument();
    });
  });

  it('renders activity feed', async () => {
    vi.spyOn(dashboardApi, 'getDashboardSummary').mockResolvedValue(mockSummary);

    renderWithRouterAndProviders(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText('Activity')).toBeInTheDocument();
    });
  });

  it('renders priority alerts widget', async () => {
    vi.spyOn(dashboardApi, 'getDashboardSummary').mockResolvedValue(mockSummary);

    renderWithRouterAndProviders(<DashboardPage />);

    await waitFor(() => {
      expect(screen.getByText('Priority Alerts')).toBeInTheDocument();
    });
  });
});
