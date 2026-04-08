import { screen } from '@testing-library/react';
import { Button } from '@/components/ui/Button';
import { renderWithProviders } from '@/test/renderWithProviders';

describe('Button', () => {
  it.each([
    { variant: 'primary' as const, expectedClass: 'bg-primary' },
    { variant: 'secondary' as const, expectedClass: 'bg-surface-container-high' },
    { variant: 'ghost' as const, expectedClass: 'bg-transparent' },
    { variant: 'destructive' as const, expectedClass: 'bg-error' },
  ])('renders $variant variant with correct color class', ({ variant, expectedClass }) => {
    renderWithProviders(<Button variant={variant}>Click</Button>);
    const button = screen.getByRole('button', { name: 'Click' });
    expect(button).toHaveClass(expectedClass);
  });

  it('renders primary variant by default', () => {
    renderWithProviders(<Button>Default</Button>);
    const button = screen.getByRole('button', { name: 'Default' });
    expect(button).toHaveClass('bg-primary');
  });

  it('does not use old secondary-container or on-surface tokens', () => {
    const variants = ['primary', 'secondary', 'ghost', 'destructive'] as const;

    variants.forEach((variant) => {
      const { unmount } = renderWithProviders(<Button variant={variant}>Test</Button>);
      const button = screen.getByRole('button', { name: 'Test' });
      const classes = button.className;

      // These old tokens should no longer appear in any variant
      expect(classes).not.toContain('bg-secondary-container');
      expect(classes).not.toContain('text-on-secondary-container');
      expect(classes).not.toContain('text-on-surface');

      unmount();
    });
  });
});
