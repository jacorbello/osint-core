import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import { SummaryMetricCard } from './SummaryMetricCard';

describe('SummaryMetricCard', () => {
  it('renders label and count badges', () => {
    renderWithProviders(
      <SummaryMetricCard label="Alerts" counts={{ open: 12, acked: 4 }} />
    );

    expect(screen.getByText('Alerts')).toBeInTheDocument();
    expect(screen.getByText(/12/)).toBeInTheDocument();
    expect(screen.getByText(/4/)).toBeInTheDocument();
  });

  it('renders uppercase status labels', () => {
    renderWithProviders(
      <SummaryMetricCard label="Jobs" counts={{ running: 8, failed: 2 }} />
    );

    expect(screen.getByText(/RUNNING/)).toBeInTheDocument();
    expect(screen.getByText(/FAILED/)).toBeInTheDocument();
  });

  it('handles empty counts gracefully', () => {
    renderWithProviders(<SummaryMetricCard label="Watches" counts={{}} />);

    expect(screen.getByText('Watches')).toBeInTheDocument();
  });

  it('applies variant-specific styling for alerts', () => {
    const { container } = renderWithProviders(
      <SummaryMetricCard label="Alerts" counts={{ open: 12 }} variant="alerts" />
    );

    expect(container.querySelector('[data-variant="alerts"]')).toBeInTheDocument();
  });
});
