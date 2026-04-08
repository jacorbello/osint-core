import { useEffect, useRef, useState } from 'react';
import type { StreamEventPayload, StreamEventType } from '@/types/api/ui';

const SSE_TOPICS: StreamEventType[] = ['alert.updated', 'lead.updated', 'job.updated'];
const MAX_EVENTS = 20;

export interface SSEFeedItem extends StreamEventPayload {
  receivedAt: string;
}

export interface UseSSEFeedResult {
  events: SSEFeedItem[];
  connected: boolean;
}

export function useSSEFeed(url: string): UseSSEFeedResult {
  const [events, setEvents] = useState<SSEFeedItem[]>([]);
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    let active = true;

    function connect() {
      if (!active) return;

      const es = new EventSource(url);
      esRef.current = es;

      es.onopen = () => {
        if (active) setConnected(true);
      };

      es.onerror = () => {
        if (active) {
          setConnected(false);
          es.close();
          esRef.current = null;
          setTimeout(() => {
            if (active) connect();
          }, 5000);
        }
      };

      SSE_TOPICS.forEach((topic) => {
        es.addEventListener(topic, (event: MessageEvent) => {
          if (!active) return;
          try {
            const payload = JSON.parse(event.data as string) as StreamEventPayload;
            const item: SSEFeedItem = { ...payload, receivedAt: new Date().toISOString() };
            setEvents((prev) => [item, ...prev].slice(0, MAX_EVENTS));
          } catch {
            // malformed frame — ignore
          }
        });
      });
    }

    connect();

    return () => {
      active = false;
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
    };
  }, [url]);

  return { events, connected };
}
