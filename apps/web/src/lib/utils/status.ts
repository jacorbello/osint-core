export type AlertStatus = 'open' | 'acked' | 'escalated' | 'resolved';
export type LeadStatus = 'new' | 'reviewing' | 'qualified' | 'contacted' | 'retained' | 'declined' | 'stale';
export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'partial_success' | 'dead_letter';

export function getAlertStatusColor(status: AlertStatus): string {
  const colors: Record<AlertStatus, string> = {
    open: 'bg-error-container text-on-error-container',
    acked: 'bg-secondary-container text-on-secondary-container',
    escalated: 'bg-tertiary-container text-on-tertiary-container',
    resolved: 'bg-surface-container-high text-on-surface',
  };
  return colors[status] || colors.open;
}

export function getLeadStatusColor(status: LeadStatus): string {
  const colors: Record<LeadStatus, string> = {
    new: 'bg-primary-container text-on-primary-container',
    reviewing: 'bg-secondary-container text-on-secondary-container',
    qualified: 'bg-tertiary-container text-on-tertiary-container',
    contacted: 'bg-surface-container-high text-on-surface',
    retained: 'bg-primary text-on-primary',
    declined: 'bg-error-container text-on-error-container',
    stale: 'bg-outline-variant text-on-surface-variant',
  };
  return colors[status] || colors.new;
}

export function getJobStatusColor(status: JobStatus): string {
  const colors: Record<JobStatus, string> = {
    queued: 'bg-surface-container-high text-on-surface',
    running: 'bg-secondary-container text-on-secondary-container',
    succeeded: 'bg-primary text-on-primary',
    failed: 'bg-error-container text-on-error-container',
    partial_success: 'bg-tertiary-container text-on-tertiary-container',
    dead_letter: 'bg-error text-on-error',
  };
  return colors[status] || colors.queued;
}
