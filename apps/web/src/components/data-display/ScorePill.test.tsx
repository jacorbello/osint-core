import { screen } from '@testing-library/react';
import { ScorePill } from '@/components/data-display/ScorePill';
import { renderWithProviders } from '@/test/renderWithProviders';

describe('ScorePill', () => {
  it.each([
    { score: 0.9, expectedText: '0.90', expectedClass: 'bg-error', description: 'critical score (>= 0.8)' },
    { score: 0.8, expectedText: '0.80', expectedClass: 'bg-error', description: 'boundary critical score (= 0.8)' },
    { score: 0.7, expectedText: '0.70', expectedClass: 'bg-warning-container', description: 'high score (>= 0.6)' },
    { score: 0.6, expectedText: '0.60', expectedClass: 'bg-warning-container', description: 'boundary high score (= 0.6)' },
    { score: 0.5, expectedText: '0.50', expectedClass: 'bg-primary-container', description: 'medium score (>= 0.4)' },
    { score: 0.4, expectedText: '0.40', expectedClass: 'bg-primary-container', description: 'boundary medium score (= 0.4)' },
    { score: 0.2, expectedText: '0.20', expectedClass: 'bg-success-container', description: 'low score (< 0.4)' },
    { score: 0.0, expectedText: '0.00', expectedClass: 'bg-success-container', description: 'zero score' },
  ])('renders $description with correct color', ({ score, expectedText, expectedClass }) => {
    renderWithProviders(<ScorePill score={score} />);
    const pill = screen.getByText(expectedText);
    expect(pill).toHaveClass(expectedClass);
  });

  it('does not use old tertiary-container or secondary-container tokens', () => {
    const testCases = [
      { score: 0.9, text: '0.90' },
      { score: 0.7, text: '0.70' },
      { score: 0.5, text: '0.50' },
      { score: 0.2, text: '0.20' },
    ];

    testCases.forEach(({ score, text }) => {
      const { unmount } = renderWithProviders(<ScorePill score={score} />);
      const pill = screen.getByText(text);
      const classes = pill.className;

      expect(classes).not.toContain('bg-tertiary-container');
      expect(classes).not.toContain('text-on-tertiary-container');
      expect(classes).not.toContain('bg-secondary-container');
      expect(classes).not.toContain('text-on-secondary-container');

      unmount();
    });
  });
});
