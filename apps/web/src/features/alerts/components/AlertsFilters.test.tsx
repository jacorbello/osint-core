import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { AlertsFilters } from './AlertsFilters';
import type { SeverityEnum, StatusEnum } from '@/types/api/common';

describe('AlertsFilters', () => {
  const defaultProps = {
    selectedSeverities: [] as SeverityEnum[],
    onSeveritiesChange: vi.fn(),
    selectedStatus: undefined as StatusEnum | undefined,
    onStatusChange: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders all severity toggles', () => {
    renderWithProviders(<AlertsFilters {...defaultProps} />);

    expect(screen.getByTestId('severity-toggle-critical')).toBeInTheDocument();
    expect(screen.getByTestId('severity-toggle-high')).toBeInTheDocument();
    expect(screen.getByTestId('severity-toggle-medium')).toBeInTheDocument();
    expect(screen.getByTestId('severity-toggle-low')).toBeInTheDocument();
    expect(screen.getByTestId('severity-toggle-info')).toBeInTheDocument();
  });

  it('renders all status toggles', () => {
    renderWithProviders(<AlertsFilters {...defaultProps} />);

    expect(screen.getByTestId('status-toggle-open')).toBeInTheDocument();
    expect(screen.getByTestId('status-toggle-acked')).toBeInTheDocument();
    expect(screen.getByTestId('status-toggle-escalated')).toBeInTheDocument();
    expect(screen.getByTestId('status-toggle-resolved')).toBeInTheDocument();
  });

  it('calls onSeveritiesChange when severity toggle clicked', async () => {
    const user = userEvent.setup();
    const onSeveritiesChange = vi.fn();

    renderWithProviders(
      <AlertsFilters {...defaultProps} onSeveritiesChange={onSeveritiesChange} />
    );

    await user.click(screen.getByTestId('severity-toggle-critical'));
    expect(onSeveritiesChange).toHaveBeenCalledWith(['critical']);
  });

  it('removes severity from selection when already selected', async () => {
    const user = userEvent.setup();
    const onSeveritiesChange = vi.fn();

    renderWithProviders(
      <AlertsFilters
        {...defaultProps}
        selectedSeverities={['critical', 'high']}
        onSeveritiesChange={onSeveritiesChange}
      />
    );

    await user.click(screen.getByTestId('severity-toggle-critical'));
    expect(onSeveritiesChange).toHaveBeenCalledWith(['high']);
  });

  it('calls onStatusChange when status toggle clicked', async () => {
    const user = userEvent.setup();
    const onStatusChange = vi.fn();

    renderWithProviders(
      <AlertsFilters {...defaultProps} onStatusChange={onStatusChange} />
    );

    await user.click(screen.getByTestId('status-toggle-open'));
    expect(onStatusChange).toHaveBeenCalledWith('open');
  });

  it('deselects status when same status clicked again', async () => {
    const user = userEvent.setup();
    const onStatusChange = vi.fn();

    renderWithProviders(
      <AlertsFilters
        {...defaultProps}
        selectedStatus="open"
        onStatusChange={onStatusChange}
      />
    );

    await user.click(screen.getByTestId('status-toggle-open'));
    expect(onStatusChange).toHaveBeenCalledWith(undefined);
  });

  it('supports multi-select for severities', async () => {
    const user = userEvent.setup();
    const onSeveritiesChange = vi.fn();

    renderWithProviders(
      <AlertsFilters
        {...defaultProps}
        selectedSeverities={['critical']}
        onSeveritiesChange={onSeveritiesChange}
      />
    );

    await user.click(screen.getByTestId('severity-toggle-high'));
    expect(onSeveritiesChange).toHaveBeenCalledWith(['critical', 'high']);
  });
});
