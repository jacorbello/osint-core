import { screen } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { TopBar } from '@/components/layout/TopBar';
import { renderWithRouterAndProviders } from '@/test/renderWithProviders';
import { vi, describe, it, expect, beforeEach } from 'vitest';

// Mock useSSEFeed
const mockUseSSEFeed = vi.fn();
vi.mock('@/features/stream/hooks/useSSEFeed', () => ({
  useSSEFeed: (...args: unknown[]) => mockUseSSEFeed(...args),
}));

function renderTopBar(route: string) {
  return renderWithRouterAndProviders(
    <Routes>
      <Route path="*" element={<TopBar />} />
    </Routes>,
    { router: { initialEntries: [route] } }
  );
}

describe('TopBar', () => {
  beforeEach(() => {
    mockUseSSEFeed.mockReturnValue({ events: [], connected: true });
  });

  describe('dynamic page title', () => {
    it.each([
      ['/', 'Overview'],
      ['/dashboard', 'Overview'],
      ['/watches', 'Watches'],
      ['/alerts', 'Alerts'],
      ['/leads', 'Leads'],
      ['/sources', 'Sources'],
      ['/investigations', 'Investigations'],
      ['/entities', 'Entities'],
      ['/reports', 'Reports'],
      ['/exports', 'Exports'],
      ['/map', 'Intelligence Map'],
      ['/settings', 'Settings'],
    ])('renders "%s" as "%s"', (route, expectedTitle) => {
      renderTopBar(route);
      expect(screen.getByRole('heading', { name: expectedTitle })).toBeTruthy();
    });

    it('renders parent title for nested routes', () => {
      renderTopBar('/investigations/abc-123');
      expect(screen.getByRole('heading', { name: 'Investigations' })).toBeTruthy();
    });

    it('falls back to "Overview" for unknown routes', () => {
      renderTopBar('/unknown');
      expect(screen.getByRole('heading', { name: 'Overview' })).toBeTruthy();
    });
  });

  describe('Cmd+K search trigger', () => {
    it('renders a clickable search trigger', () => {
      renderTopBar('/');
      const searchButton = screen.getByRole('button', { name: 'Open search' });
      expect(searchButton).toBeTruthy();
    });
  });

  describe('connection status', () => {
    it('shows "Connected" when SSE is connected', () => {
      mockUseSSEFeed.mockReturnValue({ events: [], connected: true });
      renderTopBar('/');
      expect(screen.getByText('Connected')).toBeTruthy();
    });

    it('shows "Disconnected" when SSE is not connected', () => {
      mockUseSSEFeed.mockReturnValue({ events: [], connected: false });
      renderTopBar('/');
      expect(screen.getByText('Disconnected')).toBeTruthy();
    });
  });

  describe('notification bell', () => {
    it('renders notification button with indicator', () => {
      renderTopBar('/');
      expect(screen.getByRole('button', { name: 'Notifications' })).toBeTruthy();
      expect(screen.getByTestId('notification-indicator')).toBeTruthy();
    });
  });

  describe('removed elements', () => {
    it('does not render SENTINEL NODE text', () => {
      renderTopBar('/');
      expect(screen.queryByText('SENTINEL NODE')).toBeNull();
    });

    it('does not render context tabs', () => {
      renderTopBar('/');
      expect(screen.queryByText('Global')).toBeNull();
      expect(screen.queryByText('Tactical')).toBeNull();
      expect(screen.queryByText('Strategic')).toBeNull();
    });

    it('does not contain animate-pulse class', () => {
      const { container } = renderTopBar('/');
      const pulsing = container.querySelector('.animate-pulse');
      expect(pulsing).toBeNull();
    });

    it('does not contain backdrop-blur', () => {
      const { container } = renderTopBar('/');
      const blurred = container.querySelector('[class*="backdrop-blur"]');
      expect(blurred).toBeNull();
    });
  });

  describe('height and background', () => {
    it('has 44px height and solid bg-surface background', () => {
      const { container } = renderTopBar('/');
      const header = container.querySelector('header');
      expect(header?.className).toContain('h-[44px]');
      expect(header?.className).toContain('bg-surface');
      expect(header?.className).not.toContain('bg-surface/');
    });

    it('is not fixed positioned (grid child)', () => {
      const { container } = renderTopBar('/');
      const header = container.querySelector('header');
      expect(header?.className).not.toContain('fixed');
    });
  });
});
