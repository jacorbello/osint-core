import { screen } from '@testing-library/react';
import { renderWithProviders } from '@/test/renderWithProviders';
import { StatusCard } from './StatusCard';

describe('StatusCard', () => {
  it('renders label and count', () => {
    renderWithProviders(
      <StatusCard label="Open Alerts" count={12} breakdowns={[]} />
    );

    expect(screen.getByText('Open Alerts')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
  });

  it('renders breakdown items with correct colors', () => {
    renderWithProviders(
      <StatusCard
        label="Open Alerts"
        count={7}
        breakdowns={[
          { label: 'critical', count: 2, color: 'critical' },
          { label: 'high', count: 3, color: 'warning' },
          { label: 'medium', count: 2, color: 'primary' },
        ]}
      />
    );

    expect(screen.getByText(/2 critical/)).toBeInTheDocument();
    expect(screen.getByText(/3 high/)).toBeInTheDocument();
    expect(screen.getByText(/2 medium/)).toBeInTheDocument();
  });

  it('count turns red when critical items present', () => {
    renderWithProviders(
      <StatusCard
        label="Alerts"
        count={5}
        breakdowns={[
          { label: 'critical', count: 2, color: 'critical' },
          { label: 'high', count: 3, color: 'warning' },
        ]}
      />
    );

    const countEl = screen.getByTestId('status-card-count');
    expect(countEl).toHaveClass('text-critical');
  });

  it('count uses default color when no critical items', () => {
    renderWithProviders(
      <StatusCard
        label="Active Leads"
        count={10}
        breakdowns={[
          { label: 'new', count: 5, color: 'primary' },
          { label: 'reviewing', count: 5, color: 'text-secondary' },
        ]}
      />
    );

    const countEl = screen.getByTestId('status-card-count');
    expect(countEl).toHaveClass('text-text-primary');
  });

  it('handles empty breakdowns gracefully', () => {
    renderWithProviders(
      <StatusCard label="Watches" count={0} breakdowns={[]} />
    );

    expect(screen.getByText('Watches')).toBeInTheDocument();
    expect(screen.getByText('0')).toBeInTheDocument();
    expect(screen.queryByTestId('status-card-breakdowns')).not.toBeInTheDocument();
  });

  it('applies custom className', () => {
    const { container } = renderWithProviders(
      <StatusCard label="Jobs" count={3} breakdowns={[]} className="custom-class" />
    );

    expect(container.firstChild).toHaveClass('custom-class');
  });
});
