import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouterAndProviders } from '@/test/renderWithProviders';
import { IntelligenceMapPage } from './IntelligenceMapPage';
import * as alertsApi from '@/features/alerts/api/alertsApi';
import * as leadsApi from '@/features/leads/api/leadsApi';
import * as watchesApi from '@/features/watches/api/watchesApi';
import type { AlertResponse, AlertList } from '@/types/api/alert';
import type { LeadResponse, LeadList } from '@/types/api/lead';
import type { WatchResponse, WatchList } from '@/types/api/watch';

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

vi.mock('@/features/alerts/api/alertsApi');
vi.mock('@/features/leads/api/leadsApi');
vi.mock('@/features/watches/api/watchesApi');

function makeAlert(overrides: Partial<AlertResponse> = {}): AlertResponse {
  return {
    id: crypto.randomUUID(),
    fingerprint: 'fp-test',
    severity: 'high',
    title: 'Test alert',
    summary: 'Alert summary',
    event_ids: [],
    indicator_ids: [],
    entity_ids: [],
    route_name: 'watch-1',
    status: 'open',
    occurrences: 3,
    first_fired_at: '2026-04-01T10:00:00Z',
    last_fired_at: '2026-04-08T12:00:00Z',
    acked_at: null,
    acked_by: null,
    plan_version_id: null,
    created_at: '2026-04-01T10:00:00Z',
    ...overrides,
  };
}

function makeLead(overrides: Partial<LeadResponse> = {}): LeadResponse {
  return {
    id: crypto.randomUUID(),
    lead_type: 'incident',
    status: 'new',
    title: 'Test lead',
    summary: 'Lead summary',
    constitutional_basis: [],
    jurisdiction: 'US-CA',
    institution: null,
    severity: 'medium',
    confidence: 0.85,
    dedupe_fingerprint: 'fp-lead',
    plan_id: null,
    event_ids: [],
    entity_ids: [],
    report_id: null,
    first_surfaced_at: '2026-04-02T10:00:00Z',
    last_updated_at: '2026-04-08T12:00:00Z',
    reported_at: null,
    created_at: '2026-04-02T10:00:00Z',
    ...overrides,
  };
}

function makeAlertList(items: AlertResponse[]): AlertList {
  return { items, page: { offset: 0, limit: items.length, total: items.length, has_more: false } };
}

function makeLeadList(items: LeadResponse[]): LeadList {
  return { items, page: { offset: 0, limit: items.length, total: items.length, has_more: false } };
}

function makeWatchList(items: WatchResponse[]): WatchList {
  return { items, page: { offset: 0, limit: items.length, total: items.length, has_more: false } };
}

function setupMocks(opts: {
  alerts?: AlertResponse[];
  leads?: LeadResponse[];
  watches?: WatchResponse[];
} = {}) {
  vi.spyOn(alertsApi, 'getAlerts').mockResolvedValue(makeAlertList(opts.alerts ?? []));
  vi.spyOn(leadsApi, 'getLeads').mockResolvedValue(makeLeadList(opts.leads ?? []));
  vi.spyOn(watchesApi, 'getWatches').mockResolvedValue(makeWatchList(opts.watches ?? []));
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

  it('renders filter panel with all layer toggles', async () => {
    setupMocks();
    renderWithRouterAndProviders(<IntelligenceMapPage />);

    expect(screen.getByTestId('map-filter-panel')).toBeInTheDocument();
    expect(screen.getByTestId('layer-toggle-alerts')).toBeInTheDocument();
    expect(screen.getByTestId('layer-toggle-leads')).toBeInTheDocument();
    expect(screen.getByTestId('layer-toggle-watches')).toBeInTheDocument();
    expect(screen.getByTestId('layer-toggle-signals')).toBeInTheDocument();
  });

  it('filter state initializes with all layers on', () => {
    setupMocks();
    renderWithRouterAndProviders(<IntelligenceMapPage />);

    const alertToggle = screen.getByTestId('layer-toggle-alerts');
    const leadsToggle = screen.getByTestId('layer-toggle-leads');
    const watchesToggle = screen.getByTestId('layer-toggle-watches');
    const signalsToggle = screen.getByTestId('layer-toggle-signals');

    expect(alertToggle).toHaveAttribute('aria-pressed', 'true');
    expect(leadsToggle).toHaveAttribute('aria-pressed', 'true');
    expect(watchesToggle).toHaveAttribute('aria-pressed', 'true');
    expect(signalsToggle).toHaveAttribute('aria-pressed', 'true');
  });

  it('layer toggles toggle independently', async () => {
    const user = userEvent.setup();
    setupMocks();
    renderWithRouterAndProviders(<IntelligenceMapPage />);

    const alertToggle = screen.getByTestId('layer-toggle-alerts');
    expect(alertToggle).toHaveAttribute('aria-pressed', 'true');

    await user.click(alertToggle);
    expect(alertToggle).toHaveAttribute('aria-pressed', 'false');

    // Other toggles remain on
    expect(screen.getByTestId('layer-toggle-leads')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('layer-toggle-watches')).toHaveAttribute('aria-pressed', 'true');

    // Toggle back on
    await user.click(alertToggle);
    expect(alertToggle).toHaveAttribute('aria-pressed', 'true');
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

  it('renders markers from data', async () => {
    const alerts = [makeAlert({ title: 'Alert One' }), makeAlert({ title: 'Alert Two' })];
    const leads = [makeLead({ title: 'Lead One' })];
    setupMocks({ alerts, leads });

    renderWithRouterAndProviders(<IntelligenceMapPage />);

    await waitFor(() => {
      const markers = screen.getAllByTestId('map-marker');
      expect(markers.length).toBe(3);
    });
  });

  it('layer toggle hides markers of that type', async () => {
    const user = userEvent.setup();
    const alerts = [makeAlert({ title: 'Alert One' })];
    const leads = [makeLead({ title: 'Lead One' })];
    setupMocks({ alerts, leads });

    renderWithRouterAndProviders(<IntelligenceMapPage />);

    await waitFor(() => {
      expect(screen.getAllByTestId('map-marker').length).toBe(2);
    });

    // Turn off alerts layer
    await user.click(screen.getByTestId('layer-toggle-alerts'));

    await waitFor(() => {
      expect(screen.getAllByTestId('map-marker').length).toBe(1);
    });
  });

  it('severity filter reduces visible markers', async () => {
    const user = userEvent.setup();
    const alerts = [
      makeAlert({ title: 'Critical Alert', severity: 'critical' }),
      makeAlert({ title: 'Low Alert', severity: 'low' }),
    ];
    setupMocks({ alerts });

    renderWithRouterAndProviders(<IntelligenceMapPage />);

    await waitFor(() => {
      expect(screen.getAllByTestId('map-marker').length).toBe(2);
    });

    // Filter to only critical
    await user.click(screen.getByTestId('severity-filter-critical'));

    await waitFor(() => {
      expect(screen.getAllByTestId('map-marker').length).toBe(1);
    });
  });

  it('marker click populates selection detail', async () => {
    const user = userEvent.setup();
    const alert = makeAlert({ title: 'Clicked Alert', severity: 'high', summary: 'Alert detail text' });
    setupMocks({ alerts: [alert] });

    renderWithRouterAndProviders(<IntelligenceMapPage />);

    await waitFor(() => {
      expect(screen.getByTestId('map-marker')).toBeInTheDocument();
    });

    // Before click, no selection
    expect(screen.getByTestId('no-selection')).toBeInTheDocument();

    await user.click(screen.getByTestId('map-marker'));

    await waitFor(() => {
      expect(screen.getByTestId('selection-detail')).toBeInTheDocument();
    });

    expect(screen.getByTestId('selection-title')).toHaveTextContent('Clicked Alert');
  });

  it('selection detail shows Open link', async () => {
    const user = userEvent.setup();
    const alertId = 'alert-123';
    const alert = makeAlert({ id: alertId, title: 'Link Test' });
    setupMocks({ alerts: [alert] });

    renderWithRouterAndProviders(<IntelligenceMapPage />);

    await waitFor(() => {
      expect(screen.getByTestId('map-marker')).toBeInTheDocument();
    });

    await user.click(screen.getByTestId('map-marker'));

    await waitFor(() => {
      expect(screen.getByTestId('open-detail-link')).toBeInTheDocument();
    });

    const link = screen.getByTestId('open-detail-link');
    expect(link).toHaveAttribute('href', `/alerts/${alertId}`);
    expect(link).toHaveTextContent('Open');
  });

  it('clear selection button works', async () => {
    const user = userEvent.setup();
    const alert = makeAlert({ title: 'Clear Test' });
    setupMocks({ alerts: [alert] });

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
