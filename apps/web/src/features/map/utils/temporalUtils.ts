import type { SeverityEnum } from '@/types/api/common';

/** An event with a timestamp and severity used for histogram bucketing. */
export interface TemporalEvent {
  timestamp: string | number | Date;
  severity: SeverityEnum;
}

/** The time range emitted by the scrubber. */
export interface TimeRange {
  start: Date;
  end: Date;
}

export type PresetKey = '1h' | '24h' | '7d' | '30d' | 'custom';

export const PRESET_DURATIONS: Record<Exclude<PresetKey, 'custom'>, number> = {
  '1h': 60 * 60 * 1000,
  '24h': 24 * 60 * 60 * 1000,
  '7d': 7 * 24 * 60 * 60 * 1000,
  '30d': 30 * 24 * 60 * 60 * 1000,
};

export const SEVERITY_RANK: Record<string, number> = {
  critical: 4,
  high: 3,
  medium: 2,
  low: 1,
  info: 0,
};

export const SEVERITY_BAR_COLOR: Record<string, string> = {
  critical: 'bg-error',
  high: 'bg-warning',
  medium: 'bg-primary',
  low: 'bg-surface-container-highest',
  info: 'bg-surface-container-high',
};

export interface Bin {
  count: number;
  highestSeverity: SeverityEnum;
  start: number;
  end: number;
}

/** Bucket events into time bins and compute per-bin severity. */
export function bucketEvents(
  events: TemporalEvent[],
  rangeStart: number,
  rangeEnd: number,
  binCount: number
): Bin[] {
  const span = rangeEnd - rangeStart;
  const binWidth = span / binCount;
  const bins: Bin[] = Array.from({ length: binCount }, (_, i) => ({
    count: 0,
    highestSeverity: 'info' as SeverityEnum,
    start: rangeStart + i * binWidth,
    end: rangeStart + (i + 1) * binWidth,
  }));

  for (const event of events) {
    const ts = new Date(event.timestamp).getTime();
    if (ts < rangeStart || ts > rangeEnd) continue;
    const idx = Math.min(Math.floor((ts - rangeStart) / binWidth), binCount - 1);
    bins[idx].count += 1;
    if (
      SEVERITY_RANK[event.severity] >
      SEVERITY_RANK[bins[idx].highestSeverity]
    ) {
      bins[idx].highestSeverity = event.severity;
    }
  }

  return bins;
}

export interface TemporalScrubberProps {
  /** Events to bucket into the histogram. */
  events: TemporalEvent[];
  /** Called when the selected time range changes. */
  onChange: (range: TimeRange) => void;
  /** Number of bins for the histogram. Defaults to 24. */
  binCount?: number;
  /** Optional className for the root container. */
  className?: string;
}

/** Format a Date for display as a short label. */
export function formatTimeLabel(date: Date, spanMs: number): string {
  if (spanMs <= 24 * 60 * 60 * 1000) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
}
