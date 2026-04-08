export type Severity = 'critical' | 'high' | 'medium' | 'low' | 'info';

export function getSeverityColor(severity: Severity): string {
  const colors: Record<Severity, string> = {
    critical: 'bg-error text-on-error',
    high: 'bg-warning-container text-on-warning-container',
    medium: 'bg-primary-container text-on-primary-container',
    low: 'bg-surface-container-high text-text-tertiary',
    info: 'bg-surface-container-high text-on-surface',
  };
  return colors[severity] || colors.info;
}

export function getSeverityBorderColor(severity: Severity): string {
  const colors: Record<Severity, string> = {
    critical: 'border-error',
    high: 'border-warning',
    medium: 'border-primary',
    low: 'border-outline',
    info: 'border-outline-variant',
  };
  return colors[severity] || colors.info;
}

export function getSeverityTextColor(severity: Severity): string {
  const colors: Record<Severity, string> = {
    critical: 'text-error',
    high: 'text-warning',
    medium: 'text-primary',
    low: 'text-text-tertiary',
    info: 'text-on-surface-variant',
  };
  return colors[severity] || colors.info;
}
