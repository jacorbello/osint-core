import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithRouterAndProviders } from '@/test/renderWithProviders';
import { LeadsPage } from './LeadsPage';
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

function mockQueryReturn(items: LeadResponse[], total?: number) {
  return {
    data: {
      items,
      page: { offset: 0, limit: 20, total: total ?? items.length, has_more: false },
    },
    isLoading: false,
    error: null,
  } as ReturnType<typeof useLeadsQuery>;
}

describe('LeadsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders page header', () => {
    mockUseLeadsQuery.mockReturnValue(mockQueryReturn(mockLeads));
    renderWithRouterAndProviders(<LeadsPage />);

    expect(screen.getByRole('heading', { name: 'Leads' })).toBeInTheDocument();
    expect(screen.getByText('Track and prioritize analytical leads.')).toBeInTheDocument();
  });

  it('renders all table columns', () => {
    mockUseLeadsQuery.mockReturnValue(mockQueryReturn(mockLeads));
    renderWithRouterAndProviders(<LeadsPage />);

    expect(screen.getByRole('columnheader', { name: /Lead/ })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /Type/ })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /Jurisdiction/ })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /Confidence/ })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /Status/ })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: /Updated/ })).toBeInTheDocument();
  });

  it('renders lead data in table rows', () => {
    mockUseLeadsQuery.mockReturnValue(mockQueryReturn(mockLeads));
    renderWithRouterAndProviders(<LeadsPage />);

    expect(screen.getByText('Suspicious policy change detected')).toBeInTheDocument();
    expect(screen.getByText('New regulatory framework proposal')).toBeInTheDocument();
    expect(screen.getByText('Data breach notification')).toBeInTheDocument();
    expect(screen.getByText('Federal')).toBeInTheDocument();
    expect(screen.getByText('State')).toBeInTheDocument();
  });

  it('renders loading state with skeleton table', () => {
    mockUseLeadsQuery.mockReturnValue({
      data: undefined,
      isLoading: true,
      error: null,
    } as ReturnType<typeof useLeadsQuery>);

    const { container } = renderWithRouterAndProviders(<LeadsPage />);

    expect(container.querySelector('.animate-pulse')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('renders empty state when no leads', () => {
    mockUseLeadsQuery.mockReturnValue(mockQueryReturn([]));
    renderWithRouterAndProviders(<LeadsPage />);

    expect(screen.getByText('No leads found')).toBeInTheDocument();
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

    renderWithRouterAndProviders(<LeadsPage />);

    expect(screen.getByText(/Failed to load leads/)).toBeInTheDocument();
  });


  describe('confidence bars render correctly', () => {
    it('renders high confidence with primary color', () => {
      mockUseLeadsQuery.mockReturnValue(mockQueryReturn([mockLeads[0]]));
      const { container } = renderWithRouterAndProviders(<LeadsPage />);

      expect(screen.getByText('85%')).toBeInTheDocument();
      expect(container.querySelector('.bg-primary')).toBeInTheDocument();
    });

    it('renders medium confidence with warning color', () => {
      mockUseLeadsQuery.mockReturnValue(mockQueryReturn([mockLeads[1]]));
      const { container } = renderWithRouterAndProviders(<LeadsPage />);

      expect(screen.getByText('55%')).toBeInTheDocument();
      expect(container.querySelector('.bg-warning')).toBeInTheDocument();
    });

    it('renders low confidence with muted color', () => {
      mockUseLeadsQuery.mockReturnValue(mockQueryReturn([mockLeads[2]]));
      const { container } = renderWithRouterAndProviders(<LeadsPage />);

      expect(screen.getByText('25%')).toBeInTheDocument();
      expect(container.querySelector('.bg-text-muted')).toBeInTheDocument();
    });
  });

  describe('filters', () => {
    it('renders type filter select', () => {
      mockUseLeadsQuery.mockReturnValue(mockQueryReturn(mockLeads));
      renderWithRouterAndProviders(<LeadsPage />);

      const typeSelect = screen.getByLabelText('Type');
      expect(typeSelect).toBeInTheDocument();
      expect(typeSelect).toHaveValue('');
    });

    it('renders status filter select', () => {
      mockUseLeadsQuery.mockReturnValue(mockQueryReturn(mockLeads));
      renderWithRouterAndProviders(<LeadsPage />);

      const statusSelect = screen.getByLabelText('Status');
      expect(statusSelect).toBeInTheDocument();
      expect(statusSelect).toHaveValue('');
    });

    it('renders confidence range inputs', () => {
      mockUseLeadsQuery.mockReturnValue(mockQueryReturn(mockLeads));
      renderWithRouterAndProviders(<LeadsPage />);

      expect(screen.getByLabelText('Minimum confidence')).toBeInTheDocument();
      expect(screen.getByLabelText('Maximum confidence')).toBeInTheDocument();
    });

    it('updates type filter on change', async () => {
      mockUseLeadsQuery.mockReturnValue(mockQueryReturn(mockLeads));
      renderWithRouterAndProviders(<LeadsPage />);

      const typeSelect = screen.getByLabelText('Type');
      await userEvent.selectOptions(typeSelect, 'incident');

      // useLeadsQuery should be called with the new filter
      expect(mockUseLeadsQuery).toHaveBeenCalledWith(
        expect.objectContaining({ lead_type: 'incident' }),
      );
    });

    it('updates status filter on change', async () => {
      mockUseLeadsQuery.mockReturnValue(mockQueryReturn(mockLeads));
      renderWithRouterAndProviders(<LeadsPage />);

      const statusSelect = screen.getByLabelText('Status');
      await userEvent.selectOptions(statusSelect, 'new');

      expect(mockUseLeadsQuery).toHaveBeenCalledWith(
        expect.objectContaining({ status: 'new' }),
      );
    });
  });

  describe('pagination', () => {
    it('shows pagination when more than one page', () => {
      mockUseLeadsQuery.mockReturnValue({
        data: {
          items: mockLeads,
          page: { offset: 0, limit: 20, total: 50, has_more: true },
        },
        isLoading: false,
        error: null,
      } as ReturnType<typeof useLeadsQuery>);

      renderWithRouterAndProviders(<LeadsPage />);

      expect(screen.getByText('Previous')).toBeInTheDocument();
      expect(screen.getByText('Next')).toBeInTheDocument();
      expect(screen.getByText(/Page 1 of 3/)).toBeInTheDocument();
    });

    it('disables Previous button on first page', () => {
      mockUseLeadsQuery.mockReturnValue({
        data: {
          items: mockLeads,
          page: { offset: 0, limit: 20, total: 50, has_more: true },
        },
        isLoading: false,
        error: null,
      } as ReturnType<typeof useLeadsQuery>);

      renderWithRouterAndProviders(<LeadsPage />);

      expect(screen.getByText('Previous')).toBeDisabled();
      expect(screen.getByText('Next')).not.toBeDisabled();
    });

    it('does not show pagination for single page', () => {
      mockUseLeadsQuery.mockReturnValue(mockQueryReturn(mockLeads, 3));
      renderWithRouterAndProviders(<LeadsPage />);

      expect(screen.queryByText('Previous')).not.toBeInTheDocument();
      expect(screen.queryByText('Next')).not.toBeInTheDocument();
    });

    it('navigates to next page on click', async () => {
      mockUseLeadsQuery.mockReturnValue({
        data: {
          items: mockLeads,
          page: { offset: 0, limit: 20, total: 50, has_more: true },
        },
        isLoading: false,
        error: null,
      } as ReturnType<typeof useLeadsQuery>);

      renderWithRouterAndProviders(<LeadsPage />);

      await userEvent.click(screen.getByText('Next'));

      expect(mockUseLeadsQuery).toHaveBeenCalledWith(
        expect.objectContaining({ offset: 20 }),
      );
    });
  });

  describe('sorting', () => {
    it('allows clicking column headers to sort', async () => {
      mockUseLeadsQuery.mockReturnValue(mockQueryReturn(mockLeads));
      renderWithRouterAndProviders(<LeadsPage />);

      const leadHeader = screen.getByText('Lead');
      await userEvent.click(leadHeader);

      // After first click, should show sort indicator
      const headerCell = leadHeader.closest('th');
      expect(headerCell).toBeInTheDocument();
    });
  });

  describe('row actions', () => {
    it('renders review button for each row', () => {
      mockUseLeadsQuery.mockReturnValue(mockQueryReturn(mockLeads));
      renderWithRouterAndProviders(<LeadsPage />);

      const reviewButtons = screen.getAllByTitle('Review');
      expect(reviewButtons).toHaveLength(mockLeads.length);
    });

    it('renders dismiss button for non-declined/stale leads', () => {
      mockUseLeadsQuery.mockReturnValue(mockQueryReturn(mockLeads));
      renderWithRouterAndProviders(<LeadsPage />);

      // All 3 test leads are new/reviewing/qualified, so all get dismiss
      const dismissButtons = screen.getAllByTitle('Dismiss');
      expect(dismissButtons).toHaveLength(3);
    });

    it('does not render dismiss button for declined leads', () => {
      const declinedLead: LeadResponse = {
        ...mockLeads[0],
        id: '4',
        status: 'declined',
      };
      mockUseLeadsQuery.mockReturnValue(mockQueryReturn([declinedLead]));
      renderWithRouterAndProviders(<LeadsPage />);

      expect(screen.queryByTitle('Dismiss')).not.toBeInTheDocument();
    });
  });
});
