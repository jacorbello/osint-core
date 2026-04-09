import { screen } from '@testing-library/react';
import { renderWithRouterAndProviders } from '@/test/renderWithProviders';
import { PriorityAlertsList } from './PriorityAlertsList';
import { sortAlertsBySeverity } from '../utils/sortAlerts';
import type { AlertResponse } from '@/types/api/alert';
import type { SeverityEnum, StatusEnum } from '@/types/api/common';

function makeAlert(
  overrides: Partial<AlertResponse> & { severity: SeverityEnum }
): AlertResponse {
  return {
    id: crypto.randomUUID(),
    fingerprint: 'fp-test',
    severity: overrides.severity,
    title: overrides.title ?? `Alert ${overrides.severity}`,
    summary: null,
    event_ids: [],
    indicator_ids: [],
    entity_ids: [],
    route_name: overrides.route_name ?? null,
    status: overrides.status ?? ('open' as StatusEnum),
    occurrences: overrides.occurrences ?? 1,
    first_fired_at: overrides.first_fired_at ?? '2026-04-08T10:00:00Z',
    last_fired_at: overrides.last_fired_at ?? '2026-04-09T10:00:00Z',
    acked_at: null,
    acked_by: null,
    plan_version_id: null,
    created_at: '2026-04-08T10:00:00Z',
    ...overrides,
  };
}

const mockAlerts: AlertResponse[] = [
  makeAlert({ severity: 'low', title: 'Low alert', last_fired_at: '2026-04-09T08:00:00Z' }),
  makeAlert({ severity: 'critical', title: 'Critical alert', last_fired_at: '2026-04-09T09:00:00Z' }),
  makeAlert({ severity: 'medium', title: 'Medium alert', last_fired_at: '2026-04-09T07:00:00Z' }),
  makeAlert({ severity: 'high', title: 'High alert', last_fired_at: '2026-04-09T10:00:00Z', route_name: 'Twitter Watch' }),
];

vi.mock('@/features/alerts/api/alertsQueries');

describe('sortAlertsBySeverity', () => {
  it('sorts by severity weight (critical first) then by recency', () => {
    const sorted = sortAlertsBySeverity(mockAlerts);
    expect(sorted.map((a) => a.severity)).toEqual(['critical', 'high', 'medium', 'low']);
  });

  it('sorts same-severity alerts by most recent first', () => {
    const alerts = [
      makeAlert({ severity: 'high', title: 'Older', last_fired_at: '2026-04-09T08:00:00Z' }),
      makeAlert({ severity: 'high', title: 'Newer', last_fired_at: '2026-04-09T12:00:00Z' }),
    ];
    const sorted = sortAlertsBySeverity(alerts);
    expect(sorted[0].title).toBe('Newer');
    expect(sorted[1].title).toBe('Older');
  });
});

describe('PriorityAlertsList', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders loading skeleton', async () => {
    const { useAlertsQuery } = await import('@/features/alerts/api/alertsQueries');
    vi.mocked(useAlertsQuery).mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as ReturnType<typeof useAlertsQuery>);

    renderWithRouterAndProviders(<PriorityAlertsList />);

    expect(document.querySelectorAll('.animate-pulse').length).toBeGreaterThanOrEqual(1);
  });

  it('renders empty state when no alerts', async () => {
    const { useAlertsQuery } = await import('@/features/alerts/api/alertsQueries');
    vi.mocked(useAlertsQuery).mockReturnValue({
      data: { items: [], page: { total: 0, limit: 20, has_more: false } },
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useAlertsQuery>);

    renderWithRouterAndProviders(<PriorityAlertsList />);

    expect(screen.getByText('No alerts')).toBeInTheDocument();
    expect(screen.getByText('No priority alerts to display right now')).toBeInTheDocument();
  });

  it('renders alerts sorted by severity with correct elements', async () => {
    const { useAlertsQuery } = await import('@/features/alerts/api/alertsQueries');
    vi.mocked(useAlertsQuery).mockReturnValue({
      data: { items: mockAlerts, page: { total: 4, limit: 20, has_more: false } },
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useAlertsQuery>);

    renderWithRouterAndProviders(<PriorityAlertsList />);

    // Header with count
    expect(screen.getByText('Priority Alerts')).toBeInTheDocument();
    expect(screen.getByText('4')).toBeInTheDocument();

    // All alert titles present
    expect(screen.getByText('Critical alert')).toBeInTheDocument();
    expect(screen.getByText('High alert')).toBeInTheDocument();
    expect(screen.getByText('Medium alert')).toBeInTheDocument();
    expect(screen.getByText('Low alert')).toBeInTheDocument();

    // Watch source metadata
    expect(screen.getByText(/Twitter Watch/)).toBeInTheDocument();
  });

  it('renders severity bars with correct colors', async () => {
    const { useAlertsQuery } = await import('@/features/alerts/api/alertsQueries');
    vi.mocked(useAlertsQuery).mockReturnValue({
      data: { items: mockAlerts, page: { total: 4, limit: 20, has_more: false } },
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useAlertsQuery>);

    renderWithRouterAndProviders(<PriorityAlertsList />);

    const criticalBar = screen.getByTestId('severity-bar-critical');
    expect(criticalBar).toHaveStyle({ backgroundColor: '#e06c75' });

    const highBar = screen.getByTestId('severity-bar-high');
    expect(highBar).toHaveStyle({ backgroundColor: '#e5c07b' });

    const mediumBar = screen.getByTestId('severity-bar-medium');
    expect(mediumBar).toHaveStyle({ backgroundColor: '#5b8def' });

    const lowBar = screen.getByTestId('severity-bar-low');
    expect(lowBar).toHaveClass('bg-text-tertiary');
  });

  it('renders "View all" link pointing to /alerts', async () => {
    const { useAlertsQuery } = await import('@/features/alerts/api/alertsQueries');
    vi.mocked(useAlertsQuery).mockReturnValue({
      data: { items: [], page: { total: 0, limit: 20, has_more: false } },
      isLoading: false,
      error: null,
    } as unknown as ReturnType<typeof useAlertsQuery>);

    renderWithRouterAndProviders(<PriorityAlertsList />);

    const link = screen.getByRole('link', { name: /view all/i });
    expect(link).toHaveAttribute('href', '/alerts');
  });
});
