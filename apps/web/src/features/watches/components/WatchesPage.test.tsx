import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { WatchesPage } from './WatchesPage';
import * as watchesQueries from '../api/watchesQueries';
import type { WatchResponse } from '@/types/api/watch';

function createQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

function renderWithProviders(ui: React.ReactElement) {
  const queryClient = createQueryClient();
  return render(
    <QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>
  );
}

const mockWatch = (overrides: Partial<WatchResponse> = {}): WatchResponse => ({
  id: 'watch-1',
  name: 'Eastern Europe Monitor',
  watch_type: 'dynamic',
  status: 'active',
  region: 'Eastern Europe',
  country_codes: ['UA', 'RU'],
  bounding_box: null,
  keywords: ['conflict', 'military'],
  source_filter: null,
  severity_threshold: 'medium',
  plan_id: null,
  ttl_hours: null,
  created_at: '2026-04-01T10:00:00Z',
  expires_at: null,
  promoted_at: null,
  created_by: 'analyst',
  ...overrides,
});

describe('WatchesPage', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('shows loading skeleton while fetching', () => {
    vi.spyOn(watchesQueries, 'useWatchesListQuery').mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as ReturnType<typeof watchesQueries.useWatchesListQuery>);

    renderWithProviders(<WatchesPage />);
    expect(screen.getByTestId('watches-skeleton')).toBeInTheDocument();
  });

  it('renders empty state when no watches exist', () => {
    vi.spyOn(watchesQueries, 'useWatchesListQuery').mockReturnValue({
      data: { items: [], page: { offset: 0, limit: 50, total: 0, has_more: false } },
      isLoading: false,
      error: null,
    } as ReturnType<typeof watchesQueries.useWatchesListQuery>);

    renderWithProviders(<WatchesPage />);
    expect(screen.getByText('No watches yet')).toBeInTheDocument();
    expect(screen.getByText(/Create your first watch/)).toBeInTheDocument();
    expect(screen.getByTestId('empty-create-watch-button')).toBeInTheDocument();
  });

  it('renders watches list with correct data', () => {
    const watches = [
      mockWatch(),
      mockWatch({
        id: 'watch-2',
        name: 'Asia-Pacific Scanner',
        status: 'paused',
        keywords: ['trade', 'sanctions', 'shipping'],
      }),
    ];

    vi.spyOn(watchesQueries, 'useWatchesListQuery').mockReturnValue({
      data: { items: watches, page: { offset: 0, limit: 50, total: 2, has_more: false } },
      isLoading: false,
      error: null,
    } as ReturnType<typeof watchesQueries.useWatchesListQuery>);

    renderWithProviders(<WatchesPage />);

    expect(screen.getByTestId('watches-table')).toBeInTheDocument();
    expect(screen.getByText('Eastern Europe Monitor')).toBeInTheDocument();
    expect(screen.getByText('Asia-Pacific Scanner')).toBeInTheDocument();
    expect(screen.getAllByTestId('watch-row')).toHaveLength(2);
  });

  it('shows correct status indicator colors', () => {
    const watches = [
      mockWatch({ id: 'w1', status: 'active' }),
      mockWatch({ id: 'w2', name: 'Paused Watch', status: 'paused' }),
      mockWatch({ id: 'w3', name: 'Expired Watch', status: 'expired' }),
    ];

    vi.spyOn(watchesQueries, 'useWatchesListQuery').mockReturnValue({
      data: { items: watches, page: { offset: 0, limit: 50, total: 3, has_more: false } },
      isLoading: false,
      error: null,
    } as ReturnType<typeof watchesQueries.useWatchesListQuery>);

    renderWithProviders(<WatchesPage />);

    const activeDot = screen.getByTestId('status-dot-active');
    const pausedDot = screen.getByTestId('status-dot-paused');
    const expiredDot = screen.getByTestId('status-dot-expired');

    expect(activeDot.className).toContain('bg-success');
    expect(pausedDot.className).toContain('bg-warning');
    expect(expiredDot.className).toContain('bg-error');
  });

  it('shows error banner on API failure', () => {
    vi.spyOn(watchesQueries, 'useWatchesListQuery').mockReturnValue({
      data: undefined,
      isLoading: false,
      error: { code: 'server_error', detail: 'Failed to fetch watches' },
    } as ReturnType<typeof watchesQueries.useWatchesListQuery>);

    renderWithProviders(<WatchesPage />);
    expect(screen.getByText('Failed to fetch watches')).toBeInTheDocument();
  });

  it('renders create watch button in header', () => {
    vi.spyOn(watchesQueries, 'useWatchesListQuery').mockReturnValue({
      data: { items: [], page: { offset: 0, limit: 50, total: 0, has_more: false } },
      isLoading: false,
      error: null,
    } as ReturnType<typeof watchesQueries.useWatchesListQuery>);

    renderWithProviders(<WatchesPage />);
    expect(screen.getByTestId('create-watch-button')).toBeInTheDocument();
    expect(screen.getByText('New Watch')).toBeInTheDocument();
  });

  it('displays page heading', () => {
    vi.spyOn(watchesQueries, 'useWatchesListQuery').mockReturnValue({
      data: { items: [], page: { offset: 0, limit: 50, total: 0, has_more: false } },
      isLoading: false,
      error: null,
    } as ReturnType<typeof watchesQueries.useWatchesListQuery>);

    renderWithProviders(<WatchesPage />);
    expect(screen.getByText('Watches')).toBeInTheDocument();
    expect(screen.getByText('Monitor targets and track collection requirements.')).toBeInTheDocument();
  });
});
