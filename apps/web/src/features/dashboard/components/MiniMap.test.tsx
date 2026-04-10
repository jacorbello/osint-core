import { screen, fireEvent } from '@testing-library/react';
import { renderWithRouterAndProviders } from '@/test/renderWithProviders';
import { MiniMap, type MapMarker } from './MiniMap';

// Mock react-leaflet components
vi.mock('react-leaflet', () => ({
  MapContainer: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="leaflet-map">{children}</div>
  ),
  TileLayer: () => <div data-testid="leaflet-tiles" />,
  CircleMarker: ({ pathOptions }: { pathOptions: { fillColor: string } }) => (
    <div data-testid="leaflet-marker" data-color={pathOptions.fillColor} />
  ),
  useMapEvents: () => null,
}));

// Mock leaflet CSS import
vi.mock('leaflet/dist/leaflet.css', () => ({}));

const mockMarkers: MapMarker[] = [
  { id: '1', lat: 40.7, lng: -74.0, type: 'alert' },
  { id: '2', lat: 51.5, lng: -0.1, type: 'lead' },
  { id: '3', lat: 35.6, lng: 139.6, type: 'watch' },
];

describe('MiniMap', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it('renders collapsed state by default with marker count', () => {
    renderWithRouterAndProviders(<MiniMap markers={mockMarkers} />);

    expect(screen.getByTestId('minimap-collapsed')).toBeInTheDocument();
    expect(screen.getByText('Map — 3 active markers')).toBeInTheDocument();
  });

  it('renders singular "marker" when count is 1', () => {
    renderWithRouterAndProviders(<MiniMap markers={[mockMarkers[0]]} />);

    expect(screen.getByText('Map — 1 active marker')).toBeInTheDocument();
  });

  it('renders 0 markers when no markers provided', () => {
    renderWithRouterAndProviders(<MiniMap />);

    expect(screen.getByText('Map — 0 active markers')).toBeInTheDocument();
  });

  it('expands when collapsed bar is clicked', () => {
    renderWithRouterAndProviders(<MiniMap markers={mockMarkers} />);

    fireEvent.click(screen.getByTestId('minimap-collapsed'));

    expect(screen.getByTestId('minimap-expanded')).toBeInTheDocument();
    expect(screen.getByTestId('leaflet-map')).toBeInTheDocument();
  });

  it('collapses when expanded header is clicked', () => {
    renderWithRouterAndProviders(<MiniMap markers={mockMarkers} />);

    // Expand
    fireEvent.click(screen.getByTestId('minimap-collapsed'));
    expect(screen.getByTestId('minimap-expanded')).toBeInTheDocument();

    // Collapse
    fireEvent.click(screen.getByLabelText('Collapse map'));
    expect(screen.getByTestId('minimap-collapsed')).toBeInTheDocument();
  });

  it('renders markers with correct colors per type', () => {
    renderWithRouterAndProviders(<MiniMap markers={mockMarkers} />);

    // Expand to see the map
    fireEvent.click(screen.getByTestId('minimap-collapsed'));

    const markers = screen.getAllByTestId('leaflet-marker');
    expect(markers).toHaveLength(3);

    expect(markers[0]).toHaveAttribute('data-color', '#ef4444'); // alert = red
    expect(markers[1]).toHaveAttribute('data-color', '#3b82f6'); // lead = blue
    expect(markers[2]).toHaveAttribute('data-color', '#22c55e'); // watch = green
  });

  it('persists collapsed state to localStorage', () => {
    renderWithRouterAndProviders(<MiniMap markers={mockMarkers} />);

    // Default collapsed = true
    expect(localStorage.getItem('osint-minimap-collapsed')).toBe('true');

    // Expand
    fireEvent.click(screen.getByTestId('minimap-collapsed'));
    expect(localStorage.getItem('osint-minimap-collapsed')).toBe('false');

    // Collapse again
    fireEvent.click(screen.getByLabelText('Collapse map'));
    expect(localStorage.getItem('osint-minimap-collapsed')).toBe('true');
  });

  it('reads initial state from localStorage', () => {
    localStorage.setItem('osint-minimap-collapsed', 'false');

    renderWithRouterAndProviders(<MiniMap markers={mockMarkers} />);

    expect(screen.getByTestId('minimap-expanded')).toBeInTheDocument();
  });

  it('shows empty state when expanded with no markers', () => {
    renderWithRouterAndProviders(<MiniMap markers={[]} />);

    // Expand
    fireEvent.click(screen.getByTestId('minimap-collapsed'));

    expect(screen.getByTestId('minimap-empty')).toBeInTheDocument();
    expect(screen.getByText('No geo data available')).toBeInTheDocument();
  });

  it('has correct aria attributes in collapsed state', () => {
    renderWithRouterAndProviders(<MiniMap />);

    const collapsed = screen.getByTestId('minimap-collapsed');
    expect(collapsed).toHaveAttribute('aria-expanded', 'false');
    expect(collapsed).toHaveAttribute('aria-label', 'Expand map');
    expect(collapsed).toHaveAttribute('role', 'button');
  });

  it('has correct aria attributes in expanded state', () => {
    renderWithRouterAndProviders(<MiniMap markers={mockMarkers} />);

    fireEvent.click(screen.getByTestId('minimap-collapsed'));

    const collapseBtn = screen.getByLabelText('Collapse map');
    expect(collapseBtn).toHaveAttribute('aria-expanded', 'true');
    expect(collapseBtn).toHaveAttribute('role', 'button');
  });
});
