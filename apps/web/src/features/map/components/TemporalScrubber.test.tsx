import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/renderWithProviders';
import { TemporalScrubber } from './TemporalScrubber';
import { bucketEvents, type TemporalEvent, type TimeRange } from '../utils/temporalUtils';

/* ------------------------------------------------------------------ */
/*  Unit: bucketEvents                                                */
/* ------------------------------------------------------------------ */

describe('bucketEvents', () => {
  const BASE = new Date('2026-04-10T00:00:00Z').getTime();
  const HOUR = 60 * 60 * 1000;

  it('returns the requested number of bins', () => {
    const bins = bucketEvents([], BASE, BASE + 24 * HOUR, 24);
    expect(bins).toHaveLength(24);
  });

  it('counts events into the correct bins', () => {
    const events: TemporalEvent[] = [
      { timestamp: new Date(BASE + 0.5 * HOUR).toISOString(), severity: 'low' },
      { timestamp: new Date(BASE + 0.7 * HOUR).toISOString(), severity: 'low' },
      { timestamp: new Date(BASE + 2.3 * HOUR).toISOString(), severity: 'medium' },
    ];
    const bins = bucketEvents(events, BASE, BASE + 24 * HOUR, 24);
    expect(bins[0].count).toBe(2);
    expect(bins[2].count).toBe(1);
    expect(bins[1].count).toBe(0);
  });

  it('sets bar heights proportional to event counts', () => {
    const events: TemporalEvent[] = [
      { timestamp: new Date(BASE + 0.1 * HOUR).toISOString(), severity: 'low' },
      { timestamp: new Date(BASE + 0.2 * HOUR).toISOString(), severity: 'low' },
      { timestamp: new Date(BASE + 0.3 * HOUR).toISOString(), severity: 'low' },
      { timestamp: new Date(BASE + 0.4 * HOUR).toISOString(), severity: 'low' },
      { timestamp: new Date(BASE + 1.5 * HOUR).toISOString(), severity: 'low' },
      { timestamp: new Date(BASE + 1.6 * HOUR).toISOString(), severity: 'low' },
    ];
    const bins = bucketEvents(events, BASE, BASE + 24 * HOUR, 24);
    // Bin 0 has 4 events, bin 1 has 2 — ratio should be 2:1
    expect(bins[0].count).toBe(4);
    expect(bins[1].count).toBe(2);
    expect(bins[0].count / bins[1].count).toBe(2);
  });

  it('assigns highest severity per bin', () => {
    const events: TemporalEvent[] = [
      { timestamp: new Date(BASE + 0.1 * HOUR).toISOString(), severity: 'low' },
      { timestamp: new Date(BASE + 0.2 * HOUR).toISOString(), severity: 'critical' },
      { timestamp: new Date(BASE + 1.5 * HOUR).toISOString(), severity: 'medium' },
      { timestamp: new Date(BASE + 1.6 * HOUR).toISOString(), severity: 'high' },
    ];
    const bins = bucketEvents(events, BASE, BASE + 24 * HOUR, 24);
    expect(bins[0].highestSeverity).toBe('critical');
    expect(bins[1].highestSeverity).toBe('high');
  });

  it('ignores events outside the range', () => {
    const events: TemporalEvent[] = [
      { timestamp: new Date(BASE - HOUR).toISOString(), severity: 'low' },
      { timestamp: new Date(BASE + 25 * HOUR).toISOString(), severity: 'low' },
    ];
    const bins = bucketEvents(events, BASE, BASE + 24 * HOUR, 24);
    const total = bins.reduce((s, b) => s + b.count, 0);
    expect(total).toBe(0);
  });

  it('defaults empty bins to info severity', () => {
    const bins = bucketEvents([], BASE, BASE + 24 * HOUR, 4);
    bins.forEach((bin) => {
      expect(bin.highestSeverity).toBe('info');
    });
  });
});

/* ------------------------------------------------------------------ */
/*  Component: TemporalScrubber                                       */
/* ------------------------------------------------------------------ */

describe('TemporalScrubber', () => {
  const HOUR = 60 * 60 * 1000;
  const NOW = new Date('2026-04-10T12:00:00Z').getTime();

  it('renders the scrubber container', () => {
    renderWithProviders(
      <TemporalScrubber events={[]} onChange={vi.fn()} initialNow={NOW} />
    );
    expect(screen.getByTestId('temporal-scrubber')).toBeInTheDocument();
  });

  it('renders the correct number of histogram bars', () => {
    renderWithProviders(
      <TemporalScrubber events={[]} onChange={vi.fn()} binCount={12} initialNow={NOW} />
    );
    const histogram = screen.getByTestId('histogram');
    const bars = within(histogram).getAllByTestId(/^histogram-bar-/);
    expect(bars).toHaveLength(12);
  });

  it('renders default 24 histogram bars', () => {
    renderWithProviders(
      <TemporalScrubber events={[]} onChange={vi.fn()} initialNow={NOW} />
    );
    const histogram = screen.getByTestId('histogram');
    const bars = within(histogram).getAllByTestId(/^histogram-bar-/);
    expect(bars).toHaveLength(24);
  });

  it('colors bars by highest severity (data attribute)', () => {
    // Place events in the first bin (bin 0 covers -24h to -23h)
    const events: TemporalEvent[] = [
      { timestamp: new Date(NOW - 23.5 * HOUR).toISOString(), severity: 'critical' },
      { timestamp: new Date(NOW - 23.5 * HOUR + 1000).toISOString(), severity: 'low' },
    ];
    renderWithProviders(
      <TemporalScrubber events={events} onChange={vi.fn()} initialNow={NOW} />
    );
    const bar0 = screen.getByTestId('histogram-bar-0');
    expect(bar0.getAttribute('data-severity')).toBe('critical');
  });

  it('renders all preset buttons', () => {
    renderWithProviders(
      <TemporalScrubber events={[]} onChange={vi.fn()} initialNow={NOW} />
    );
    expect(screen.getByTestId('preset-1h')).toBeInTheDocument();
    expect(screen.getByTestId('preset-24h')).toBeInTheDocument();
    expect(screen.getByTestId('preset-7d')).toBeInTheDocument();
    expect(screen.getByTestId('preset-30d')).toBeInTheDocument();
  });

  it('calls onChange when a preset button is clicked', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderWithProviders(
      <TemporalScrubber events={[]} onChange={onChange} initialNow={NOW} />
    );
    await user.click(screen.getByTestId('preset-1h'));
    expect(onChange).toHaveBeenCalledTimes(1);
    const range: TimeRange = onChange.mock.calls[0][0];
    expect(range.start).toBeInstanceOf(Date);
    expect(range.end).toBeInstanceOf(Date);
    // 1h preset: end - start should be ~1 hour
    const diff = range.end.getTime() - range.start.getTime();
    expect(diff).toBe(HOUR);
  });

  it('preset 7d sets correct time range', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderWithProviders(
      <TemporalScrubber events={[]} onChange={onChange} initialNow={NOW} />
    );
    await user.click(screen.getByTestId('preset-7d'));
    expect(onChange).toHaveBeenCalledTimes(1);
    const range: TimeRange = onChange.mock.calls[0][0];
    const diff = range.end.getTime() - range.start.getTime();
    expect(diff).toBe(7 * 24 * HOUR);
  });

  it('renders the "Now" indicator at the right edge', () => {
    renderWithProviders(
      <TemporalScrubber events={[]} onChange={vi.fn()} initialNow={NOW} />
    );
    const nowIndicator = screen.getByTestId('now-indicator');
    expect(nowIndicator).toBeInTheDocument();
    expect(nowIndicator.textContent).toBe('Now');
  });

  it('renders time labels at appropriate intervals', () => {
    renderWithProviders(
      <TemporalScrubber events={[]} onChange={vi.fn()} initialNow={NOW} />
    );
    const labels = screen.getByTestId('time-labels');
    expect(labels).toBeInTheDocument();
    // Should have 5 labels total (4 time + 1 "Now")
    expect(within(labels).getAllByTestId(/^time-label-|now-indicator/)).toHaveLength(5);
  });

  it('renders slider with two thumbs', () => {
    renderWithProviders(
      <TemporalScrubber events={[]} onChange={vi.fn()} initialNow={NOW} />
    );
    expect(screen.getByTestId('slider-thumb-start')).toBeInTheDocument();
    expect(screen.getByTestId('slider-thumb-end')).toBeInTheDocument();
  });

  it('displays selected range text', () => {
    renderWithProviders(
      <TemporalScrubber events={[]} onChange={vi.fn()} initialNow={NOW} />
    );
    expect(screen.getByTestId('range-display')).toBeInTheDocument();
  });

  it('is responsive to container width via className prop', () => {
    renderWithProviders(
      <TemporalScrubber events={[]} onChange={vi.fn()} className="w-full" initialNow={NOW} />
    );
    const scrubber = screen.getByTestId('temporal-scrubber');
    expect(scrubber.className).toContain('w-full');
  });
});
