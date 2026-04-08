import { cn } from '@/lib/utils/cn';
import { formatRelativeTime } from '@/lib/utils/format';
import { useSSEFeed } from '@/features/stream/hooks/useSSEFeed';
import type { StreamEventType } from '@/types/api/ui';

const TOPIC_CONFIG: Record<
  StreamEventType,
  { label: string; icon: string; badgeClass: string }
> = {
  'alert.updated': {
    label: 'ALERT',
    icon: 'warning',
    badgeClass: 'bg-error-container/30 text-error',
  },
  'lead.updated': {
    label: 'LEAD',
    icon: 'person_pin_circle',
    badgeClass: 'bg-primary-container/20 text-primary',
  },
  'job.updated': {
    label: 'JOB',
    icon: 'cyclone',
    badgeClass: 'bg-secondary-container/20 text-on-secondary-container',
  },
};

export function RealtimeActivityRail() {
  const { events, connected } = useSSEFeed('/api/v1/stream');

  return (
    <aside className="w-80 flex flex-col bg-surface-container rounded-lg border border-outline-variant/10 overflow-hidden flex-shrink-0">
      <div className="p-3 border-b border-outline-variant/10 flex justify-between items-center bg-surface-container-high flex-shrink-0">
        <h3 className="text-[11px] font-bold uppercase tracking-widest text-on-surface">
          Realtime Activity
        </h3>
        <div className="flex items-center gap-2">
          <span
            className={cn(
              'w-1.5 h-1.5 rounded-full',
              connected ? 'bg-primary animate-pulse' : 'bg-error'
            )}
          />
          <span className="text-[9px] font-bold uppercase tracking-wider text-outline">
            {connected ? 'ACTIVE' : 'DISCONNECTED'}
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-2 flex flex-col gap-2">
        {events.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-center py-8 px-4">
            <span className="material-symbols-outlined text-4xl text-outline mb-2">stream</span>
            <p className="text-[11px] text-on-surface-variant">
              {connected ? 'Waiting for events…' : 'Connecting to stream…'}
            </p>
          </div>
        )}

        {events.map((event) => {
          const config = TOPIC_CONFIG[event.type] ?? {
            label: event.type,
            icon: 'info',
            badgeClass: 'bg-surface-container-highest text-on-surface-variant',
          };
          const toStatus = event.payload?.to_status as string | undefined;

          return (
            <div
              key={`${event.id}-${event.receivedAt}`}
              className="bg-surface-container-high rounded-lg p-2.5 border border-outline-variant/10"
            >
              <div className="flex items-start gap-2">
                <span
                  className={cn(
                    'material-symbols-outlined text-base mt-0.5 flex-shrink-0',
                    config.badgeClass.split(' ')[1]
                  )}
                >
                  {config.icon}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5 mb-0.5">
                    <span
                      className={cn(
                        'text-[8px] font-bold px-1 py-0.5 rounded',
                        config.badgeClass
                      )}
                    >
                      {config.label}
                    </span>
                    {toStatus && (
                      <span className="text-[9px] text-on-surface-variant">
                        → {toStatus.toUpperCase()}
                      </span>
                    )}
                  </div>
                  <p className="text-[10px] font-mono text-on-surface-variant truncate">
                    {event.id.slice(0, 8)}…
                  </p>
                  <p className="text-[9px] text-outline mt-0.5">
                    {formatRelativeTime(event.timestamp)}
                  </p>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </aside>
  );
}
