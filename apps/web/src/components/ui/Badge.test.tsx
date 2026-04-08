import { screen } from '@testing-library/react';
import { Badge } from '@/components/ui/Badge';
import { renderWithProviders } from '@/test/renderWithProviders';

describe('Badge', () => {
  it.each([
    { variant: 'default' as const, expectedClass: 'bg-surface-container-high' },
    { variant: 'primary' as const, expectedClass: 'bg-primary-container' },
    { variant: 'secondary' as const, expectedClass: 'bg-surface-container' },
    { variant: 'tertiary' as const, expectedClass: 'bg-warning-container' },
    { variant: 'error' as const, expectedClass: 'bg-error-container' },
  ])('renders $variant variant with correct color class', ({ variant, expectedClass }) => {
    renderWithProviders(<Badge variant={variant}>Label</Badge>);
    const badge = screen.getByText('Label');
    expect(badge).toHaveClass(expectedClass);
  });

  it('renders default variant when no variant specified', () => {
    renderWithProviders(<Badge>Default</Badge>);
    const badge = screen.getByText('Default');
    expect(badge).toHaveClass('bg-surface-container-high');
  });

  it('does not use old secondary-container or tertiary-container tokens', () => {
    const variants = ['default', 'primary', 'secondary', 'tertiary', 'error'] as const;

    variants.forEach((variant) => {
      const { unmount } = renderWithProviders(<Badge variant={variant}>Test</Badge>);
      const badge = screen.getByText('Test');
      const classes = badge.className;

      expect(classes).not.toContain('bg-secondary-container');
      expect(classes).not.toContain('text-on-secondary-container');
      expect(classes).not.toContain('bg-tertiary-container');
      expect(classes).not.toContain('text-on-tertiary-container');

      unmount();
    });
  });
});
