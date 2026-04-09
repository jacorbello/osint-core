import { useCallback, useEffect, useRef, useState } from 'react';
import { cn } from '@/lib/utils/cn';
import { formatRelativeTime } from '@/lib/utils/format';
import { useSSEFeed } from '@/features/stream/hooks/useSSEFeed';
import type { StreamEventType } from '@/types/api/ui';

const TOPIC_CONFIG: Record<
  StreamEventType,
  { label: string; icon: string; borderColor: string; badgeClass: string }
> = {
  'alert.updated': {
    label: 'ALERT',
    icon: 'warning',
    borderColor: 'border-l-critical',
    badgeClass: 'bg-error-container/30 text-critical',
  },
  'lead.updated': {
    label: 'LEAD',
    icon: 'person_pin_circle',
    borderColor: 'border-l-primary',
    badgeClass: 'bg-primary-container/20 text-primary',
  },
  'job.updated': {
    label: 'JOB',
    icon: 'cyclone',
    borderColor: 'border-l-success',
    badgeClass: 'bg-success-container/20 text-success',
  },
};

const DEFAULT_CONFIG = {
  label: 'EVENT',
  icon: 'info',
  borderColor: 'border-l-warning',
  badgeClass: 'bg-warning-container/20 text-warning',
};

/** Calculate events per minute from events received in the last 60 seconds. */
function useEventRate(eventTimestamps: string[]): number {
  const [rate, setRate] = useState(0);
  const timestampsRef = useRef(eventTimestamps);

  useEffect(() => {
    timestampsRef.current = eventTimestamps;
  }, [eventTimestamps]);

  const computeRate = useCallback(() => {
    const now = Date.now();
    const oneMinuteAgo = now - 60_000;
    const recentCount = timestampsRef.current.filter(
      (ts) => new Date(ts).getTime() >= oneMinuteAgo
    ).length;
    setRate(recentCount);
  }, []);

  useEffect(() => {
    computeRate();
    const interval = setInterval(computeRate, 10_000);
    return () => clearInterval(interval);
  }, [computeRate]);

  useEffect(() => {
    computeRate();
  }, [eventTimestamps.length, computeRate]);

  return rate;
}

export function ActivityFeed() {
  const { events, connected } = useSSEFeed('/api/v1/stream');
  const eventTimestamps = events.map((e) => e.receivedAt);
  const eventsPerMinute = useEventRate(eventTimestamps);

  return (
    <aside
      className="w-[280px] flex flex-col bg-surface-container rounded-lg border border-outline-variant/10 overflow-hidden flex-shrink-0"
      data-testid="activity-feed"
    >
      <div className="p-3 border-b border-outline-variant/10 flex justify-between items-center bg-surface-container-high flex-shrink-0">
        <h3 className="text-[11px] font-bold uppercase tracking-widest text-on-surface font-label">
          Activity
        </h3>
        <div className="flex items-center gap-2">
          <span
            className={cn(
              'w-1.5 h-1.5 rounded-full flex-shrink-0',
              connected ? 'bg-success' : 'bg-critical'
            )}
            data-testid="connection-dot"
          />
          <span className="text-[9px] font-bold uppercase tracking-wider text-outline font-label">
            {connected
              ? `${eventsPerMinute} events/min`
              : 'Disconnected'}
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-2 flex flex-col gap-2">
        {events.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center py-8 px-4">
            <span className="material-symbols-outlined text-4xl text-outline mb-2">
              stream
            </span>
            <p className="text-[11px] text-on-surface-variant font-body">
              {connected ? 'Waiting for events...' : 'Connecting...'}
            </p>
          </div>
        )}

        {events.map((event) => {
          const config = TOPIC_CONFIG[event.type] ?? DEFAULT_CONFIG;
          const toStatus = event.payload?.to_status as string | undefined;

          return (
            <div
              key={`${event.id}-${event.receivedAt}`}
              className={cn(
                'bg-surface-container-high rounded-lg p-2.5 border border-outline-variant/10',
                'border-l-[3px]',
                config.borderColor
              )}
              data-testid="event-card"
            >
              <div className="flex items-center gap-1.5 mb-1">
                <span
                  className={cn(
                    'text-[8px] font-bold px-1.5 py-0.5 rounded font-label',
                    config.badgeClass
                  )}
                >
                  {config.label}
                </span>
                {toStatus && (
                  <span className="text-[9px] text-on-surface-variant font-label">
                    → {toStatus.toUpperCase()}
                  </span>
                )}
                <span className="ml-auto text-[9px] text-outline font-mono">
                  {formatRelativeTime(event.timestamp)}
                </span>
              </div>
              <p className="text-[10px] font-mono text-on-surface-variant truncate">
                {event.id.slice(0, 8)}…
              </p>
            </div>
          );
        })}
      </div>
    </aside>
  );
}
