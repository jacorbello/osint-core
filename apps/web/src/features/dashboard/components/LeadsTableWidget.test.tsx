import { screen } from '@testing-library/react';
import { renderWithRouterAndProviders } from '@/test/renderWithProviders';
import { LeadsTableWidget } from './LeadsTableWidget';
import type { LeadResponse } from '@/types/api/lead';

const mockLeads: LeadResponse[] = [
  {
    id: '1',
    lead_type: 'incident',
    status: 'new',
    title: 'Suspicious policy change detected',
    summary: null,
    constitutional_basis: [],
    jurisdiction: 'Federal',
    institution: null,
    severity: null,
    confidence: 0.85,
    dedupe_fingerprint: 'fp1',
    plan_id: null,
    event_ids: [],
    entity_ids: [],
    report_id: null,
    first_surfaced_at: '2026-04-01T00:00:00Z',
    last_updated_at: '2026-04-08T12:00:00Z',
    reported_at: null,
    created_at: '2026-04-01T00:00:00Z',
  },
  {
    id: '2',
    lead_type: 'policy',
    status: 'reviewing',
    title: 'New regulatory framework proposal',
    summary: null,
    constitutional_basis: [],
    jurisdiction: 'State',
    institution: null,
    severity: null,
    confidence: 0.55,
    dedupe_fingerprint: 'fp2',
    plan_id: null,
    event_ids: [],
    entity_ids: [],
    report_id: null,
    first_surfaced_at: '2026-04-02T00:00:00Z',
    last_updated_at: '2026-04-07T10:00:00Z',
    reported_at: null,
    created_at: '2026-04-02T00:00:00Z',
  },
  {
    id: '3',
    lead_type: 'incident',
    status: 'qualified',
    title: 'Data breach notification',
    summary: null,
    constitutional_basis: [],
    jurisdiction: null,
    institution: null,
    severity: null,
    confidence: 0.25,
    dedupe_fingerprint: 'fp3',
    plan_id: null,
    event_ids: [],
    entity_ids: [],
    report_id: null,
    first_surfaced_at: '2026-04-03T00:00:00Z',
    last_updated_at: '2026-04-06T08:00:00Z',
    reported_at: null,
    created_at: '2026-04-03T00:00:00Z',
  },
];

vi.mock('@/features/leads/api/leadsQueries', () => ({
  useLeadsQuery: vi.fn(),
}));

import { useLeadsQuery } from '@/features/leads/api/leadsQueries';

const mockUseLeadsQuery = vi.mocked(useLeadsQuery);

describe('LeadsTableWidget', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders table with correct columns', () => {
    mockUseLeadsQuery.mockReturnValue({
      data: { items: mockLeads, total: 3 },
      isLoading: false,
      error: null,
    } as ReturnType<typeof useLeadsQuery>);

    renderWithRouterAndProviders(<LeadsTableWidget />);

    expect(screen.getByText('Lead')).toBeInTheDocument();
    expect(screen.getByText('Type')).toBeInTheDocument();
    expect(screen.getByText('Conf.')).toBeInTheDocument();
    expect(screen.getByText('Status')).toBeInTheDocument();
    expect(screen.getByText('Updated')).toBeInTheDocument();
  });

  it('renders lead title and type in correct columns', () => {
    mockUseLeadsQuery.mockReturnValue({
      data: { items: mockLeads, total: 3 },
      isLoading: false,
      error: null,
    } as ReturnType<typeof useLeadsQuery>);

    renderWithRouterAndProviders(<LeadsTableWidget />);

    expect(screen.getByText('Suspicious policy change detected')).toBeInTheDocument();
    expect(screen.getAllByText('INCIDENT')).toHaveLength(2);
    expect(screen.getByText('POLICY')).toBeInTheDocument();
  });

  describe('ConfidenceBar', () => {
    it('renders high confidence with primary color', () => {
      mockUseLeadsQuery.mockReturnValue({
        data: { items: [mockLeads[0]], total: 1 },
        isLoading: false,
        error: null,
      } as ReturnType<typeof useLeadsQuery>);

      const { container } = renderWithRouterAndProviders(<LeadsTableWidget />);

      expect(screen.getByText('85%')).toBeInTheDocument();
      const bar = container.querySelector('.bg-primary');
      expect(bar).toBeInTheDocument();
    });

    it('renders medium confidence with warning color', () => {
      mockUseLeadsQuery.mockReturnValue({
        data: { items: [mockLeads[1]], total: 1 },
        isLoading: false,
        error: null,
      } as ReturnType<typeof useLeadsQuery>);

      const { container } = renderWithRouterAndProviders(<LeadsTableWidget />);

      expect(screen.getByText('55%')).toBeInTheDocument();
      const bar = container.querySelector('.bg-warning');
      expect(bar).toBeInTheDocument();
    });

    it('renders low confidence with muted color', () => {
      mockUseLeadsQuery.mockReturnValue({
        data: { items: [mockLeads[2]], total: 1 },
        isLoading: false,
        error: null,
      } as ReturnType<typeof useLeadsQuery>);

      const { container } = renderWithRouterAndProviders(<LeadsTableWidget />);

      expect(screen.getByText('25%')).toBeInTheDocument();
      const bar = container.querySelector('.bg-text-muted');
      expect(bar).toBeInTheDocument();
    });
  });

  describe('StatusBadge', () => {
    it('renders new status with primary color', () => {
      mockUseLeadsQuery.mockReturnValue({
        data: { items: [mockLeads[0]], total: 1 },
        isLoading: false,
        error: null,
      } as ReturnType<typeof useLeadsQuery>);

      renderWithRouterAndProviders(<LeadsTableWidget />);

      const badge = screen.getByText('NEW');
      expect(badge).toBeInTheDocument();
      expect(badge.className).toContain('text-primary');
    });

    it('renders reviewing status with secondary color', () => {
      mockUseLeadsQuery.mockReturnValue({
        data: { items: [mockLeads[1]], total: 1 },
        isLoading: false,
        error: null,
      } as ReturnType<typeof useLeadsQuery>);

      renderWithRouterAndProviders(<LeadsTableWidget />);

      const badge = screen.getByText('REVIEWING');
      expect(badge).toBeInTheDocument();
      expect(badge.className).toContain('text-secondary');
    });

    it('renders qualified status with success color', () => {
      mockUseLeadsQuery.mockReturnValue({
        data: { items: [mockLeads[2]], total: 1 },
        isLoading: false,
        error: null,
      } as ReturnType<typeof useLeadsQuery>);

      renderWithRouterAndProviders(<LeadsTableWidget />);

      const badge = screen.getByText('QUALIFIED');
      expect(badge).toBeInTheDocument();
      expect(badge.className).toContain('text-success');
    });
  });

  it('renders "View all" link pointing to /leads', () => {
    mockUseLeadsQuery.mockReturnValue({
      data: { items: mockLeads, total: 3 },
      isLoading: false,
      error: null,
    } as ReturnType<typeof useLeadsQuery>);

    renderWithRouterAndProviders(<LeadsTableWidget />);

    const link = screen.getByRole('link', { name: /view all/i });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute('href', '/leads');
  });

  it('renders loading state with skeleton blocks', () => {
    mockUseLeadsQuery.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as ReturnType<typeof useLeadsQuery>);

    const { container } = renderWithRouterAndProviders(<LeadsTableWidget />);

    expect(container.querySelector('.animate-pulse')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('renders empty state when no leads', () => {
    mockUseLeadsQuery.mockReturnValue({
      data: { items: [], total: 0 },
      isLoading: false,
      error: null,
    } as ReturnType<typeof useLeadsQuery>);

    renderWithRouterAndProviders(<LeadsTableWidget />);

    expect(screen.getByText('No leads')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('renders error state', () => {
    mockUseLeadsQuery.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: {
        type: 'about:blank',
        title: 'Internal Server Error',
        status: 500,
        detail: 'Failed to load leads',
      },
    } as ReturnType<typeof useLeadsQuery>);

    renderWithRouterAndProviders(<LeadsTableWidget />);

    expect(screen.getByText(/Failed to load leads/)).toBeInTheDocument();
  });
});
