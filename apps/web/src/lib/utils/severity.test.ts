import { getSeverityColor, getSeverityBorderColor, getSeverityTextColor } from './severity';

describe('getSeverityColor', () => {
  it.each([
    { severity: 'critical', expected: 'bg-error text-on-error' },
    { severity: 'high', expected: 'bg-warning-container text-on-warning-container' },
    { severity: 'medium', expected: 'bg-primary-container text-on-primary-container' },
    { severity: 'low', expected: 'bg-surface-container-high text-text-tertiary' },
    { severity: 'info', expected: 'bg-surface-container-high text-on-surface' },
  ] as const)('returns correct classes for $severity', ({ severity, expected }) => {
    expect(getSeverityColor(severity)).toBe(expected);
  });

  it('falls back to info for unknown severity', () => {
    expect(getSeverityColor('unknown' as never)).toBe('bg-surface-container-high text-on-surface');
  });
});

describe('getSeverityBorderColor', () => {
  it.each([
    { severity: 'critical', expected: 'border-error' },
    { severity: 'high', expected: 'border-warning' },
    { severity: 'medium', expected: 'border-primary' },
    { severity: 'low', expected: 'border-outline' },
    { severity: 'info', expected: 'border-outline-variant' },
  ] as const)('returns correct border class for $severity', ({ severity, expected }) => {
    expect(getSeverityBorderColor(severity)).toBe(expected);
  });

  it('falls back to info for unknown severity', () => {
    expect(getSeverityBorderColor('unknown' as never)).toBe('border-outline-variant');
  });
});

describe('getSeverityTextColor', () => {
  it.each([
    { severity: 'critical', expected: 'text-error' },
    { severity: 'high', expected: 'text-warning' },
    { severity: 'medium', expected: 'text-primary' },
    { severity: 'low', expected: 'text-text-tertiary' },
    { severity: 'info', expected: 'text-on-surface-variant' },
  ] as const)('returns correct text class for $severity', ({ severity, expected }) => {
    expect(getSeverityTextColor(severity)).toBe(expected);
  });

  it('falls back to info for unknown severity', () => {
    expect(getSeverityTextColor('unknown' as never)).toBe('text-on-surface-variant');
  });
});
