import { screen } from '@testing-library/react';
import { renderWithRouterAndProviders } from '@/test/renderWithProviders';
import { DashboardPage } from './DashboardPage';

vi.mock('react-leaflet', () => ({
  MapContainer: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="leaflet-map">{children}</div>
  ),
  TileLayer: () => <div />,
  CircleMarker: () => <div />,
  useMapEvents: () => null,
}));
vi.mock('leaflet/dist/leaflet.css', () => ({}));
vi.mock('@/features/alerts/api/alertsQueries', () => ({
  useAlertsQuery: () => ({ data: undefined, isLoading: false, error: null }),
}));
vi.mock('@/features/leads/api/leadsQueries', () => ({
  useLeadsQuery: () => ({ data: undefined, isLoading: false, error: null }),
}));
vi.mock('@/features/stream/hooks/useSSEFeed', () => ({
  useSSEFeed: () => ({ events: [], connected: false }),
}));

describe('DashboardPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders the dashboard layout', () => {
    renderWithRouterAndProviders(<DashboardPage />);

    expect(screen.getByTestId('minimap-collapsed')).toBeInTheDocument();
  });

  it('renders activity feed', () => {
    renderWithRouterAndProviders(<DashboardPage />);

    expect(screen.getByText('Activity')).toBeInTheDocument();
  });

  it('renders priority alerts widget', () => {
    renderWithRouterAndProviders(<DashboardPage />);

    expect(screen.getByText('Priority Alerts')).toBeInTheDocument();
  });
});
