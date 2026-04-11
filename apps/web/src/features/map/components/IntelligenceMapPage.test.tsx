import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouterAndProviders } from '@/test/renderWithProviders';
import { IntelligenceMapPage } from './IntelligenceMapPage';
import * as eventsApi from '@/features/events/api/eventsApi';
import type { EventResponse, EventList } from '@/types/api/event';

// Mock react-leaflet since jsdom doesn't support canvas/map rendering
vi.mock('react-leaflet', () => ({
  MapContainer: ({
    children,
    'data-testid': testId,
  }: {
    children: React.ReactNode;
    'data-testid'?: string;
    [key: string]: unknown;
  }) => <div data-testid={testId}>{children}</div>,
  TileLayer: () => <div data-testid="tile-layer" />,
  Marker: ({
    eventHandlers,
  }: {
    eventHandlers?: { click?: () => void };
    [key: string]: unknown;
  }) => <div data-testid="map-marker" onClick={eventHandlers?.click} />,
  ZoomControl: () => <div data-testid="zoom-control" />,
  useMapEvents: () => ({
    getBounds: () => ({
      getSouth: () => 0,
      getWest: () => 0,
      getNorth: () => 0,
      getEast: () => 0,
    }),
  }),
}));

vi.mock('leaflet', () => ({
  default: {
    divIcon: (opts: Record<string, unknown>) => opts,
  },
}));

vi.mock('./map.css', () => ({}));
vi.mock('leaflet/dist/leaflet.css', () => ({}));

vi.mock('@/features/events/api/eventsApi');

function makeEvent(overrides: Partial<EventResponse> = {}): EventResponse {
  return {
    id: crypto.randomUUID(),
    event_type: 'acled',
    source_id: 'source-1',
    title: 'Test event',
    summary: 'Event summary',
    raw_excerpt: null,
    occurred_at: '2026-04-01T10:00:00Z',
    ingested_at: '2026-04-01T10:05:00Z',
    score: null,
    severity: 'high',
    dedupe_fingerprint: 'fp-test',
    plan_version_id: null,
    country_code: 'US',
    latitude: 38.9,
    longitude: -77.0,
    region: 'North America',
    source_category: null,
    nlp_relevance: null,
    nlp_summary: null,
    metadata: {},
    ...overrides,
  };
}

function makeEventList(items: EventResponse[]): EventList {
  return { items, page: { offset: 0, limit: items.length, total: items.length, has_more: false } };
}

function setupMocks(opts: { events?: EventResponse[] } = {}) {
  vi.spyOn(eventsApi, 'getEvents').mockResolvedValue(makeEventList(opts.events ?? []));
}

describe('IntelligenceMapPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the page with header', async () => {
    setupMocks();
    renderWithRouterAndProviders(<IntelligenceMapPage />);

    expect(screen.getByText('Intelligence Map')).toBeInTheDocument();
    expect(screen.getByText('Geospatial view of intelligence activity.')).toBeInTheDocument();
    expect(screen.getByTestId('intelligence-map-page')).toBeInTheDocument();
  });

  it('renders filter panel with events layer toggle', async () => {
    setupMocks();
    renderWithRouterAndProviders(<IntelligenceMapPage />);

    expect(screen.getByTestId('map-filter-panel')).toBeInTheDocument();
    expect(screen.getByTestId('layer-toggle-events')).toBeInTheDocument();
  });

  it('filter state initializes with events layer on', () => {
    setupMocks();
    renderWithRouterAndProviders(<IntelligenceMapPage />);

    const eventsToggle = screen.getByTestId('layer-toggle-events');
    expect(eventsToggle).toHaveAttribute('aria-pressed', 'true');
  });

  it('events layer toggle works', async () => {
    const user = userEvent.setup();
    setupMocks();
    renderWithRouterAndProviders(<IntelligenceMapPage />);

    const eventsToggle = screen.getByTestId('layer-toggle-events');
    expect(eventsToggle).toHaveAttribute('aria-pressed', 'true');

    await user.click(eventsToggle);
    expect(eventsToggle).toHaveAttribute('aria-pressed', 'false');

    await user.click(eventsToggle);
    expect(eventsToggle).toHaveAttribute('aria-pressed', 'true');
  });

  it('severity filter buttons toggle', async () => {
    const user = userEvent.setup();
    setupMocks();
    renderWithRouterAndProviders(<IntelligenceMapPage />);

    const critBtn = screen.getByTestId('severity-filter-critical');
    expect(critBtn).toHaveAttribute('aria-pressed', 'false');

    await user.click(critBtn);
    expect(critBtn).toHaveAttribute('aria-pressed', 'true');

    await user.click(critBtn);
    expect(critBtn).toHaveAttribute('aria-pressed', 'false');
  });

  it('renders markers from events with coordinates', async () => {
    const events = [
      makeEvent({ title: 'Event One', latitude: 38.9, longitude: -77.0 }),
      makeEvent({ title: 'Event Two', latitude: 51.5, longitude: -0.1 }),
    ];
    setupMocks({ events });

    renderWithRouterAndProviders(<IntelligenceMapPage />);

    await waitFor(() => {
      const markers = screen.getAllByTestId('map-marker');
      expect(markers.length).toBe(2);
    });
  });

  it('excludes events without coordinates from map', async () => {
    const events = [
      makeEvent({ title: 'With coords', latitude: 38.9, longitude: -77.0 }),
      makeEvent({ title: 'No lat', latitude: null, longitude: -77.0 }),
      makeEvent({ title: 'No lng', latitude: 38.9, longitude: null }),
      makeEvent({ title: 'No coords', latitude: null, longitude: null }),
    ];
    setupMocks({ events });

    renderWithRouterAndProviders(<IntelligenceMapPage />);

    await waitFor(() => {
      const markers = screen.getAllByTestId('map-marker');
      expect(markers.length).toBe(1);
    });
  });

  it('events layer toggle hides all markers', async () => {
    const user = userEvent.setup();
    const events = [
      makeEvent({ title: 'Event One', latitude: 38.9, longitude: -77.0 }),
      makeEvent({ title: 'Event Two', latitude: 51.5, longitude: -0.1 }),
    ];
    setupMocks({ events });

    renderWithRouterAndProviders(<IntelligenceMapPage />);

    await waitFor(() => {
      expect(screen.getAllByTestId('map-marker').length).toBe(2);
    });

    await user.click(screen.getByTestId('layer-toggle-events'));

    await waitFor(() => {
      expect(screen.queryAllByTestId('map-marker').length).toBe(0);
    });
  });

  it('severity filter reduces visible markers', async () => {
    const user = userEvent.setup();
    const events = [
      makeEvent({ title: 'Critical Event', severity: 'critical', latitude: 38.9, longitude: -77.0 }),
      makeEvent({ title: 'Low Event', severity: 'low', latitude: 51.5, longitude: -0.1 }),
    ];
    setupMocks({ events });

    renderWithRouterAndProviders(<IntelligenceMapPage />);

    await waitFor(() => {
      expect(screen.getAllByTestId('map-marker').length).toBe(2);
    });

    await user.click(screen.getByTestId('severity-filter-critical'));

    await waitFor(() => {
      expect(screen.getAllByTestId('map-marker').length).toBe(1);
    });
  });

  it('marker click populates selection detail', async () => {
    const user = userEvent.setup();
    const event = makeEvent({ title: 'Clicked Event', severity: 'high', summary: 'Event detail text' });
    setupMocks({ events: [event] });

    renderWithRouterAndProviders(<IntelligenceMapPage />);

    await waitFor(() => {
      expect(screen.getByTestId('map-marker')).toBeInTheDocument();
    });

    expect(screen.getByTestId('no-selection')).toBeInTheDocument();

    await user.click(screen.getByTestId('map-marker'));

    await waitFor(() => {
      expect(screen.getByTestId('selection-detail')).toBeInTheDocument();
    });

    expect(screen.getByTestId('selection-title')).toHaveTextContent('Clicked Event');
  });

  it('selection detail shows Open link to events page', async () => {
    const user = userEvent.setup();
    const eventId = 'event-123';
    const event = makeEvent({ id: eventId, title: 'Link Test' });
    setupMocks({ events: [event] });

    renderWithRouterAndProviders(<IntelligenceMapPage />);

    await waitFor(() => {
      expect(screen.getByTestId('map-marker')).toBeInTheDocument();
    });

    await user.click(screen.getByTestId('map-marker'));

    await waitFor(() => {
      expect(screen.getByTestId('open-detail-link')).toBeInTheDocument();
    });

    const link = screen.getByTestId('open-detail-link');
    expect(link).toHaveAttribute('href', `/${eventId}`);
    expect(link).toHaveTextContent('Open');
  });

  it('clear selection button works', async () => {
    const user = userEvent.setup();
    const event = makeEvent({ title: 'Clear Test' });
    setupMocks({ events: [event] });

    renderWithRouterAndProviders(<IntelligenceMapPage />);

    await waitFor(() => {
      expect(screen.getByTestId('map-marker')).toBeInTheDocument();
    });

    await user.click(screen.getByTestId('map-marker'));

    await waitFor(() => {
      expect(screen.getByTestId('selection-detail')).toBeInTheDocument();
    });

    await user.click(screen.getByTestId('clear-selection'));

    await waitFor(() => {
      expect(screen.getByTestId('no-selection')).toBeInTheDocument();
    });
  });

  it('renders the map canvas', async () => {
    setupMocks();
    renderWithRouterAndProviders(<IntelligenceMapPage />);

    expect(screen.getByTestId('map-canvas')).toBeInTheDocument();
  });

  it('renders zoom control', async () => {
    setupMocks();
    renderWithRouterAndProviders(<IntelligenceMapPage />);

    expect(screen.getByTestId('zoom-control')).toBeInTheDocument();
  });
});
