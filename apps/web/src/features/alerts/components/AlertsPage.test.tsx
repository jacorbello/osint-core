import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouterAndProviders } from '@/test/renderWithProviders';
import { AlertsPage } from './AlertsPage';
import * as alertsApi from '../api/alertsApi';
import type { AlertList } from '@/types/api/alert';
import type { AlertResponse } from '@/types/api/alert';

vi.mock('../api/alertsApi');

function makeAlert(overrides: Partial<AlertResponse> = {}): AlertResponse {
  return {
    id: crypto.randomUUID(),
    fingerprint: 'fp-test',
    severity: 'high',
    title: 'Test alert',
    summary: null,
    event_ids: [],
    indicator_ids: [],
    entity_ids: [],
    route_name: 'watch-1',
    status: 'open',
    occurrences: 3,
    first_fired_at: '2026-04-01T10:00:00Z',
    last_fired_at: '2026-04-08T12:00:00Z',
    acked_at: null,
    acked_by: null,
    plan_version_id: null,
    created_at: '2026-04-01T10:00:00Z',
    ...overrides,
  };
}

function makeMockData(items: AlertResponse[], total?: number): AlertList {
  return {
    items,
    page: {
      offset: 0,
      limit: items.length,
      total: total ?? items.length,
      has_more: (total ?? items.length) > items.length,
    },
  };
}

describe('AlertsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the page header', async () => {
    vi.spyOn(alertsApi, 'getAlerts').mockResolvedValue(makeMockData([]));

    renderWithRouterAndProviders(<AlertsPage />);

    expect(screen.getByText('Alerts')).toBeInTheDocument();
    expect(screen.getByText('Review and triage intelligence alerts.')).toBeInTheDocument();
  });

  it('shows loading skeleton while fetching', () => {
    vi.spyOn(alertsApi, 'getAlerts').mockImplementation(() => new Promise(() => {}));

    renderWithRouterAndProviders(<AlertsPage />);

    expect(document.querySelector('.animate-pulse')).toBeInTheDocument();
  });

  it('shows empty state when no alerts', async () => {
    vi.spyOn(alertsApi, 'getAlerts').mockResolvedValue(makeMockData([]));

    renderWithRouterAndProviders(<AlertsPage />);

    await waitFor(() => {
      expect(screen.getByText('No alerts')).toBeInTheDocument();
    });
    expect(screen.getByText('No alerts to display.')).toBeInTheDocument();
  });

  it('renders alerts in a table with correct columns', async () => {
    const alerts = [
      makeAlert({ title: 'Critical breach detected', severity: 'critical', occurrences: 42 }),
      makeAlert({ title: 'Suspicious login', severity: 'medium', status: 'acked' }),
    ];
    vi.spyOn(alertsApi, 'getAlerts').mockResolvedValue(makeMockData(alerts));

    renderWithRouterAndProviders(<AlertsPage />);

    await waitFor(() => {
      expect(screen.getByTestId('alerts-table')).toBeInTheDocument();
    });

    expect(screen.getByText('Critical breach detected')).toBeInTheDocument();
    expect(screen.getByText('Suspicious login')).toBeInTheDocument();
    expect(screen.getByText('CRITICAL')).toBeInTheDocument();
    expect(screen.getByText('MEDIUM')).toBeInTheDocument();

    const rows = screen.getAllByTestId('alert-row');
    expect(rows).toHaveLength(2);
  });

  it('shows error banner on API failure', async () => {
    vi.spyOn(alertsApi, 'getAlerts').mockRejectedValue({
      code: 'INTERNAL',
      detail: 'Something went wrong',
    });

    renderWithRouterAndProviders(<AlertsPage />);

    await waitFor(() => {
      expect(screen.getByText(/Something went wrong/)).toBeInTheDocument();
    });
  });

  it('severity filter toggles work as multi-select', async () => {
    const user = userEvent.setup();
    const alerts = [
      makeAlert({ severity: 'critical', title: 'Crit alert' }),
      makeAlert({ severity: 'low', title: 'Low alert' }),
    ];
    vi.spyOn(alertsApi, 'getAlerts').mockResolvedValue(makeMockData(alerts));

    renderWithRouterAndProviders(<AlertsPage />);

    await waitFor(() => {
      expect(screen.getByTestId('alerts-table')).toBeInTheDocument();
    });

    const criticalToggle = screen.getByTestId('severity-toggle-critical');
    await user.click(criticalToggle);

    // After clicking critical, the query should be called with severity: 'critical'
    await waitFor(() => {
      expect(alertsApi.getAlerts).toHaveBeenCalledWith(
        expect.objectContaining({ severity: 'critical' })
      );
    });

    // Click again to deselect
    await user.click(criticalToggle);
    await waitFor(() => {
      expect(alertsApi.getAlerts).toHaveBeenCalledWith(
        expect.objectContaining({ severity: undefined })
      );
    });
  });

  it('status filter toggles work', async () => {
    const user = userEvent.setup();
    const alerts = [makeAlert({ status: 'open' })];
    vi.spyOn(alertsApi, 'getAlerts').mockResolvedValue(makeMockData(alerts));

    renderWithRouterAndProviders(<AlertsPage />);

    await waitFor(() => {
      expect(screen.getByTestId('alerts-filters')).toBeInTheDocument();
    });

    const openToggle = screen.getByTestId('status-toggle-open');
    await user.click(openToggle);

    await waitFor(() => {
      expect(alertsApi.getAlerts).toHaveBeenCalledWith(
        expect.objectContaining({ status: 'open' })
      );
    });

    // Click again to deselect
    await user.click(openToggle);
    await waitFor(() => {
      expect(alertsApi.getAlerts).toHaveBeenCalledWith(
        expect.objectContaining({ status: undefined })
      );
    });
  });

  it('pagination controls work', async () => {
    const alerts = Array.from({ length: 10 }, (_, i) =>
      makeAlert({ title: `Alert ${i}` })
    );
    vi.spyOn(alertsApi, 'getAlerts').mockResolvedValue(makeMockData(alerts, 30));

    renderWithRouterAndProviders(<AlertsPage />);

    await waitFor(() => {
      expect(screen.getByTestId('pagination-controls')).toBeInTheDocument();
    });

    expect(screen.getByTestId('page-info')).toHaveTextContent('Page 1 of 3');

    const prevBtn = screen.getByTestId('prev-page-btn');
    expect(prevBtn).toBeDisabled();

    const nextBtn = screen.getByTestId('next-page-btn');
    expect(nextBtn).not.toBeDisabled();
  });

  it('page size select changes rows per page', async () => {
    const user = userEvent.setup();
    const alerts = Array.from({ length: 10 }, (_, i) =>
      makeAlert({ title: `Alert ${i}` })
    );
    vi.spyOn(alertsApi, 'getAlerts').mockResolvedValue(makeMockData(alerts, 50));

    renderWithRouterAndProviders(<AlertsPage />);

    await waitFor(() => {
      expect(screen.getByTestId('page-size-select')).toBeInTheDocument();
    });

    const select = screen.getByTestId('page-size-select');
    await user.selectOptions(select, '25');

    await waitFor(() => {
      expect(alertsApi.getAlerts).toHaveBeenCalledWith(
        expect.objectContaining({ limit: 25 })
      );
    });
  });

  it('column headers are sortable', async () => {
    const user = userEvent.setup();
    const alerts = [
      makeAlert({ title: 'Alpha', severity: 'low' }),
      makeAlert({ title: 'Beta', severity: 'critical' }),
    ];
    vi.spyOn(alertsApi, 'getAlerts').mockResolvedValue(makeMockData(alerts));

    renderWithRouterAndProviders(<AlertsPage />);

    await waitFor(() => {
      expect(screen.getByTestId('alerts-table')).toBeInTheDocument();
    });

    const severityHeader = screen.getByTestId('sort-header-severity');
    await user.click(severityHeader);

    // After sorting, the table should have sort indicators
    await waitFor(() => {
      const sortIndicator = within(severityHeader).queryByText('arrow_upward');
      expect(sortIndicator).toBeInTheDocument();
    });
  });

  it('severity color bars render on left edge of rows', async () => {
    const alerts = [makeAlert({ severity: 'critical' })];
    vi.spyOn(alertsApi, 'getAlerts').mockResolvedValue(makeMockData(alerts));

    renderWithRouterAndProviders(<AlertsPage />);

    await waitFor(() => {
      expect(screen.getByTestId('alerts-table')).toBeInTheDocument();
    });

    const row = screen.getByTestId('alert-row');
    const firstCell = row.querySelector('td');
    expect(firstCell?.className).toContain('border-l-[3px]');
    expect(firstCell?.className).toContain('border-error');
  });

  it('shows filtered empty state message when filters active', async () => {
    const user = userEvent.setup();
    vi.spyOn(alertsApi, 'getAlerts').mockResolvedValue(makeMockData([]));

    renderWithRouterAndProviders(<AlertsPage />);

    await waitFor(() => {
      expect(screen.getByTestId('alerts-filters')).toBeInTheDocument();
    });

    const criticalToggle = screen.getByTestId('severity-toggle-critical');
    await user.click(criticalToggle);

    await waitFor(() => {
      expect(
        screen.getByText('No alerts match the current filters. Try adjusting your filters.')
      ).toBeInTheDocument();
    });
  });
});
