import { useCallback, useMemo, useState } from 'react';
import * as Slider from '@radix-ui/react-slider';
import { cn } from '@/lib/utils/cn';
import {
  bucketEvents,
  formatTimeLabel,
  PRESET_DURATIONS,
  SEVERITY_BAR_COLOR,
  type PresetKey,
  type TemporalEvent,
  type TemporalScrubberProps,
  type TimeRange,
} from '../utils/temporalUtils';

export type { TemporalEvent, TimeRange, PresetKey, TemporalScrubberProps };

export function TemporalScrubber({
  events,
  onChange,
  binCount = 24,
  className,
  initialNow,
}: TemporalScrubberProps & { initialNow?: number }) {
  const [now] = useState(() => initialNow ?? Date.now());
  const [activePreset, setActivePreset] = useState<PresetKey>('24h');
  const [rangeStart, setRangeStart] = useState(now - PRESET_DURATIONS['24h']);
  const [rangeEnd, setRangeEnd] = useState(now);
  const [sliderValues, setSliderValues] = useState<[number, number]>([0, 100]);

  const bins = useMemo(
    () => bucketEvents(events, rangeStart, rangeEnd, binCount),
    [events, rangeStart, rangeEnd, binCount]
  );

  const maxCount = useMemo(
    () => Math.max(...bins.map((b) => b.count), 1),
    [bins]
  );

  const selectedStart = useMemo(() => {
    const span = rangeEnd - rangeStart;
    return new Date(rangeStart + (sliderValues[0] / 100) * span);
  }, [rangeStart, rangeEnd, sliderValues]);

  const selectedEnd = useMemo(() => {
    const span = rangeEnd - rangeStart;
    return new Date(rangeStart + (sliderValues[1] / 100) * span);
  }, [rangeStart, rangeEnd, sliderValues]);

  const handlePresetClick = useCallback(
    (preset: Exclude<PresetKey, 'custom'>) => {
      const duration = PRESET_DURATIONS[preset];
      const newStart = now - duration;
      setRangeStart(newStart);
      setRangeEnd(now);
      setSliderValues([0, 100]);
      setActivePreset(preset);
      onChange({ start: new Date(newStart), end: new Date(now) });
    },
    [now, onChange]
  );

  const handleSliderChange = useCallback(
    (values: number[]) => {
      const newValues: [number, number] = [values[0], values[1]];
      setSliderValues(newValues);
      const span = rangeEnd - rangeStart;
      const start = new Date(rangeStart + (newValues[0] / 100) * span);
      const end = new Date(rangeStart + (newValues[1] / 100) * span);
      onChange({ start, end });
    },
    [rangeStart, rangeEnd, onChange]
  );

  const span = rangeEnd - rangeStart;
  const labelCount = 5;
  const timeLabels = useMemo(
    () =>
      Array.from({ length: labelCount }, (_, i) => {
        const t = rangeStart + (i / (labelCount - 1)) * span;
        return {
          label:
            i === labelCount - 1
              ? 'Now'
              : formatTimeLabel(new Date(t), span),
          position: (i / (labelCount - 1)) * 100,
        };
      }),
    [rangeStart, span, labelCount]
  );

  return (
    <div
      data-testid="temporal-scrubber"
      className={cn(
        'flex flex-col gap-1.5 rounded-md bg-surface-container p-3 h-[80px]',
        className
      )}
    >
      {/* Top row: presets + selected range display */}
      <div className="flex items-center justify-between text-[10px] font-label text-on-surface-variant">
        <div className="flex gap-1">
          {(Object.keys(PRESET_DURATIONS) as Array<Exclude<PresetKey, 'custom'>>).map(
            (preset) => (
              <button
                key={preset}
                data-testid={`preset-${preset}`}
                onClick={() => handlePresetClick(preset)}
                className={cn(
                  'rounded px-1.5 py-0.5 uppercase tracking-wide transition-colors',
                  activePreset === preset
                    ? 'bg-primary text-on-primary'
                    : 'bg-surface-container-high text-on-surface-variant hover:bg-surface-bright'
                )}
              >
                {preset}
              </button>
            )
          )}
        </div>
        <span className="font-mono text-[10px] text-text-secondary" data-testid="range-display">
          {selectedStart.toLocaleString()} — {selectedEnd.toLocaleString()}
        </span>
      </div>

      {/* Histogram + Slider overlay */}
      <div className="relative flex-1 min-h-0">
        {/* Histogram bars */}
        <div
          className="flex items-end gap-px h-full w-full"
          data-testid="histogram"
          role="img"
          aria-label="Event density histogram"
        >
          {bins.map((bin, i) => {
            const heightPct = bin.count === 0 ? 0 : Math.max((bin.count / maxCount) * 100, 4);
            return (
              <div
                key={i}
                data-testid={`histogram-bar-${i}`}
                data-severity={bin.highestSeverity}
                className={cn(
                  'flex-1 rounded-t-sm transition-all',
                  bin.count === 0
                    ? 'bg-surface-container-low'
                    : SEVERITY_BAR_COLOR[bin.highestSeverity] ?? 'bg-surface-container-high'
                )}
                style={{ height: `${heightPct}%` }}
              />
            );
          })}
        </div>

        {/* Range slider overlay */}
        <Slider.Root
          className="absolute inset-0 flex items-center"
          data-testid="range-slider"
          min={0}
          max={100}
          step={1}
          value={sliderValues}
          onValueChange={handleSliderChange}
          aria-label="Time range selector"
        >
          <Slider.Track className="relative h-full w-full">
            <Slider.Range className="absolute h-full bg-primary/10 rounded-sm" />
          </Slider.Track>
          <Slider.Thumb
            data-testid="slider-thumb-start"
            className="block h-full w-1.5 rounded-sm bg-primary/80 cursor-ew-resize
                       hover:bg-primary focus:outline-none focus:ring-1 focus:ring-primary"
            aria-label="Range start"
          />
          <Slider.Thumb
            data-testid="slider-thumb-end"
            className="block h-full w-1.5 rounded-sm bg-primary/80 cursor-ew-resize
                       hover:bg-primary focus:outline-none focus:ring-1 focus:ring-primary"
            aria-label="Range end"
          />
        </Slider.Root>
      </div>

      {/* Time labels */}
      <div className="relative h-3" data-testid="time-labels">
        {timeLabels.map((tl, i) => (
          <span
            key={i}
            className={cn(
              'absolute text-[9px] font-mono text-text-tertiary -translate-x-1/2',
              i === timeLabels.length - 1 && 'text-primary font-semibold'
            )}
            style={{ left: `${tl.position}%` }}
            data-testid={i === timeLabels.length - 1 ? 'now-indicator' : `time-label-${i}`}
          >
            {tl.label}
          </span>
        ))}
      </div>
    </div>
  );
}
