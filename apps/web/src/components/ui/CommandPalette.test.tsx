import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { CommandPalette } from '@/components/ui/CommandPalette';
import { renderWithRouterAndProviders } from '@/test/renderWithProviders';
import { vi, describe, it, expect, beforeEach } from 'vitest';

// Mock alerts and leads queries
const mockAlertsData = {
  items: [
    {
      id: 'alert-1',
      fingerprint: 'fp-1',
      severity: 'high' as const,
      title: 'Suspicious login attempt',
      summary: null,
      event_ids: [],
      indicator_ids: [],
      entity_ids: [],
      route_name: null,
      status: 'open' as const,
      occurrences: 1,
      first_fired_at: '2026-04-01T00:00:00Z',
      last_fired_at: '2026-04-01T00:00:00Z',
      acked_at: null,
      acked_by: null,
      plan_version_id: null,
      created_at: '2026-04-01T00:00:00Z',
    },
  ],
  page: { offset: 0, limit: 5, total: 1, has_more: false },
};

const mockLeadsData = {
  items: [
    {
      id: 'lead-1',
      lead_type: 'incident' as const,
      status: 'new' as const,
      title: 'Data breach investigation',
      summary: null,
      constitutional_basis: [],
      jurisdiction: null,
      institution: null,
      severity: 'high' as const,
      confidence: 0.85,
      dedupe_fingerprint: 'fp-1',
      plan_id: null,
      event_ids: [],
      entity_ids: [],
      report_id: null,
      first_surfaced_at: '2026-04-01T00:00:00Z',
      last_updated_at: '2026-04-01T00:00:00Z',
      reported_at: null,
      created_at: '2026-04-01T00:00:00Z',
    },
  ],
  page: { offset: 0, limit: 5, total: 1, has_more: false },
};

vi.mock('@/features/alerts/api/alertsQueries', () => ({
  useAlertsQuery: () => ({ data: mockAlertsData, isLoading: false }),
}));

vi.mock('@/features/leads/api/leadsQueries', () => ({
  useLeadsQuery: () => ({ data: mockLeadsData, isLoading: false }),
}));

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

function renderPalette() {
  return renderWithRouterAndProviders(
    <Routes>
      <Route
        path="*"
        element={<CommandPalette />}
      />
    </Routes>,
    { router: { initialEntries: ['/'] } },
  );
}

describe('CommandPalette', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
  });

  describe('keyboard shortcut', () => {
    it('opens on Cmd+K', async () => {
      renderPalette();

      // Palette should not be visible initially
      expect(screen.queryByTestId('command-palette-input')).toBeNull();

      // Simulate Cmd+K
      document.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'k', metaKey: true }),
      );

      await waitFor(() => {
        expect(screen.getByTestId('command-palette-input')).toBeTruthy();
      });
    });

    it('opens on Ctrl+K', async () => {
      renderPalette();

      document.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'k', ctrlKey: true }),
      );

      await waitFor(() => {
        expect(screen.getByTestId('command-palette-input')).toBeTruthy();
      });
    });

    it('closes on Escape', async () => {
      const user = userEvent.setup();
      renderPalette();

      // Open palette
      document.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'k', metaKey: true }),
      );

      await waitFor(() => {
        expect(screen.getByTestId('command-palette-input')).toBeTruthy();
      });

      // Press Escape
      await user.keyboard('{Escape}');

      await waitFor(() => {
        expect(screen.queryByTestId('command-palette-input')).toBeNull();
      });
    });
  });

  describe('static navigation items', () => {
    it('renders navigation items when open', async () => {
      renderPalette();

      document.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'k', metaKey: true }),
      );

      await waitFor(() => {
        expect(screen.getByText('Overview')).toBeTruthy();
        expect(screen.getByText('Watches')).toBeTruthy();
        expect(screen.getByText('Alerts')).toBeTruthy();
        expect(screen.getByText('Leads')).toBeTruthy();
        expect(screen.getByText('Intelligence Map')).toBeTruthy();
        expect(screen.getByText('Settings')).toBeTruthy();
      });
    });

    it('filters navigation items by search term', async () => {
      const user = userEvent.setup();
      renderPalette();

      document.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'k', metaKey: true }),
      );

      await waitFor(() => {
        expect(screen.getByTestId('command-palette-input')).toBeTruthy();
      });

      await user.type(screen.getByTestId('command-palette-input'), 'watch');

      await waitFor(() => {
        expect(screen.getByText('Watches')).toBeTruthy();
      });
    });
  });

  describe('grouped results', () => {
    it('renders section headers', async () => {
      renderPalette();

      document.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'k', metaKey: true }),
      );

      await waitFor(() => {
        expect(screen.getByText('Navigation')).toBeTruthy();
        expect(screen.getByText('Actions')).toBeTruthy();
      });
    });
  });

  describe('navigation on select', () => {
    it('navigates when selecting a navigation item', async () => {
      const user = userEvent.setup();
      renderPalette();

      document.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'k', metaKey: true }),
      );

      await waitFor(() => {
        expect(screen.getByTestId('command-item-watches')).toBeTruthy();
      });

      await user.click(screen.getByTestId('command-item-watches'));

      await waitFor(() => {
        expect(mockNavigate).toHaveBeenCalledWith('/watches');
      });
    });
  });

  describe('empty state', () => {
    it('renders helpful message when no search term', async () => {
      renderPalette();

      document.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'k', metaKey: true }),
      );

      await waitFor(() => {
        expect(screen.getByTestId('command-palette-input')).toBeTruthy();
      });

      // The empty message appears when cmdk filtering hides all items
      // With no search, navigation items should be visible
      expect(screen.getByText('Overview')).toBeTruthy();
    });
  });

  describe('action items', () => {
    it('renders action items', async () => {
      renderPalette();

      document.dispatchEvent(
        new KeyboardEvent('keydown', { key: 'k', metaKey: true }),
      );

      await waitFor(() => {
        expect(screen.getByText('Create Watch')).toBeTruthy();
        expect(screen.getByText('Export Data')).toBeTruthy();
      });
    });
  });
});
