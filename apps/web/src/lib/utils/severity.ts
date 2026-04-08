export type Severity = 'critical' | 'high' | 'medium' | 'low' | 'info';

export function getSeverityColor(severity: Severity): string {
  const colors: Record<Severity, string> = {
    critical: 'bg-error text-on-error',
    high: 'bg-tertiary-container text-on-tertiary-container',
    medium: 'bg-secondary-container text-on-secondary-container',
    low: 'bg-primary-container text-on-primary-container',
    info: 'bg-surface-container-high text-on-surface',
  };
  return colors[severity] || colors.info;
}

export function getSeverityBorderColor(severity: Severity): string {
  const colors: Record<Severity, string> = {
    critical: 'border-error',
    high: 'border-tertiary-container',
    medium: 'border-secondary-container',
    low: 'border-primary-container',
    info: 'border-outline-variant',
  };
  return colors[severity] || colors.info;
}

export function getSeverityTextColor(severity: Severity): string {
  const colors: Record<Severity, string> = {
    critical: 'text-error',
    high: 'text-tertiary-container',
    medium: 'text-secondary-container',
    low: 'text-primary-container',
    info: 'text-on-surface-variant',
  };
  return colors[severity] || colors.info;
}
