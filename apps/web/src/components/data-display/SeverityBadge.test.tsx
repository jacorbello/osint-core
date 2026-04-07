import { screen } from '@testing-library/react';
import { SeverityBadge } from '@/components/data-display/SeverityBadge';
import { renderWithProviders } from '@/test/renderWithProviders';

describe('SeverityBadge', () => {
  it.each([
    { severity: 'critical', expectedClass: 'bg-error' },
    { severity: 'high', expectedClass: 'bg-tertiary-container' },
    { severity: 'medium', expectedClass: 'bg-secondary-container' },
    { severity: 'low', expectedClass: 'bg-primary-container' },
    { severity: 'info', expectedClass: 'bg-surface-container-high' },
  ] as const)(
    'renders $severity severity with expected visual class',
    ({ severity, expectedClass }) => {
      renderWithProviders(<SeverityBadge severity={severity} />);

      const badge = screen.getByText(severity);
      expect(badge).toBeInTheDocument();
      expect(badge).toHaveClass(expectedClass);
      expect(badge).toHaveClass('uppercase');
    }
  );
});
