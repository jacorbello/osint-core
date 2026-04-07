import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import { SummaryStrip } from './SummaryStrip';
import type { DashboardSummaryResponse } from '@/types/api/ui';

describe('SummaryStrip', () => {
  const mockSummary: DashboardSummaryResponse = {
    alerts: { open: 12, acked: 4, escalated: 2 },
    leads: { new: 8, active: 15, archived: 3 },
    jobs: { running: 2, completed: 45, failed: 1 },
    watches: { active: 10 },
    events: { last_24h_count: 1234 },
    updated_at: '2026-04-07T12:00:00Z',
  };

  it('renders all metric cards from summary response', () => {
    renderWithProviders(<SummaryStrip summary={mockSummary} />);

    expect(screen.getByText('Alerts')).toBeInTheDocument();
    expect(screen.getByText('Leads')).toBeInTheDocument();
    expect(screen.getByText('Jobs')).toBeInTheDocument();
    expect(screen.getByText('Watches')).toBeInTheDocument();
    expect(screen.getByText('Events (24h)')).toBeInTheDocument();
  });

  it('displays alert counts correctly', () => {
    renderWithProviders(<SummaryStrip summary={mockSummary} />);

    expect(screen.getByText(/12/)).toBeInTheDocument();
    expect(screen.getByText(/OPEN/)).toBeInTheDocument();
  });

  it('displays events count for last 24h', () => {
    renderWithProviders(<SummaryStrip summary={mockSummary} />);

    expect(screen.getByText(/1,234/)).toBeInTheDocument();
  });

  it('handles empty counts gracefully', () => {
    const emptySummary: DashboardSummaryResponse = {
      alerts: {},
      leads: {},
      jobs: {},
      watches: {},
      events: { last_24h_count: 0 },
      updated_at: '2026-04-07T12:00:00Z',
    };

    renderWithProviders(<SummaryStrip summary={emptySummary} />);

    expect(screen.getByText('Alerts')).toBeInTheDocument();
    expect(screen.getByText('Leads')).toBeInTheDocument();
  });

  it('shows loading skeleton when isLoading is true', () => {
    const { container } = renderWithProviders(
      <SummaryStrip summary={mockSummary} isLoading={true} />
    );

    expect(container.querySelector('.animate-pulse')).toBeInTheDocument();
  });

  it('shows error banner when error is provided', () => {
    const error = {
      type: 'about:blank',
      title: 'Internal Server Error',
      status: 500,
      code: 'INTERNAL_ERROR',
      detail: 'Failed to fetch dashboard summary',
    };

    renderWithProviders(<SummaryStrip summary={mockSummary} error={error} />);

    expect(screen.getByText(/Failed to fetch dashboard summary/)).toBeInTheDocument();
  });
});
