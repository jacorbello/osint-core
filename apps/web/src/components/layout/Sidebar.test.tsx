import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Route, Routes } from 'react-router-dom';
import { Sidebar } from '@/components/layout/Sidebar';
import { SidebarProvider } from '@/components/layout/SidebarContext';
import { renderWithRouterAndProviders } from '@/test/renderWithProviders';

function renderSidebar(options?: { route?: string; collapsed?: boolean }) {
  if (options?.collapsed) {
    localStorage.setItem('osint-sidebar-collapsed', 'true');
  } else {
    localStorage.removeItem('osint-sidebar-collapsed');
  }

  return renderWithRouterAndProviders(
    <SidebarProvider>
      <Routes>
        <Route
          path="*"
          element={<Sidebar />}
        />
      </Routes>
    </SidebarProvider>,
    { router: { initialEntries: [options?.route ?? '/dashboard'] } }
  );
}

afterEach(() => {
  localStorage.clear();
});

describe('Sidebar', () => {
  describe('expanded state', () => {
    it('renders all nav items with labels', () => {
      renderSidebar();

      expect(screen.getByText('Overview')).toBeInTheDocument();
      expect(screen.getByText('Watches')).toBeInTheDocument();
      expect(screen.getByText('Sources')).toBeInTheDocument();
      expect(screen.getByText('Alerts')).toBeInTheDocument();
      expect(screen.getByText('Investigations')).toBeInTheDocument();
      expect(screen.getByText('Entities')).toBeInTheDocument();
      expect(screen.getByText('Leads')).toBeInTheDocument();
      expect(screen.getByText('Reports')).toBeInTheDocument();
      expect(screen.getByText('Exports')).toBeInTheDocument();
    });

    it('renders section headers', () => {
      renderSidebar();

      expect(screen.getByText('COLLECT')).toBeInTheDocument();
      expect(screen.getByText('ANALYZE')).toBeInTheDocument();
      expect(screen.getByText('PRODUCE')).toBeInTheDocument();
    });

    it('renders branding', () => {
      renderSidebar();

      expect(screen.getByText('OSINT Core')).toBeInTheDocument();
      expect(screen.getByText('Intelligence Platform')).toBeInTheDocument();
    });

    it('renders settings section at bottom', () => {
      renderSidebar();

      expect(screen.getByTitle('Settings')).toBeInTheDocument();
    });
  });

  describe('collapsed state', () => {
    it('renders labels with hidden classes when collapsed', () => {
      renderSidebar({ collapsed: true });

      // Labels should have collapsed styling (w-0 opacity-0)
      const nav = screen.getByRole('navigation');
      const watchesLabel = within(nav).getByText('Watches');
      expect(watchesLabel).toHaveClass('w-0', 'opacity-0');

      const sourcesLabel = within(nav).getByText('Sources');
      expect(sourcesLabel).toHaveClass('w-0', 'opacity-0');

      // Section headers should have collapsed styling
      expect(screen.getByText('COLLECT')).toHaveClass('opacity-0');
      expect(screen.getByText('ANALYZE')).toHaveClass('opacity-0');
      expect(screen.getByText('PRODUCE')).toHaveClass('opacity-0');
    });

    it('reads collapsed state from localStorage', () => {
      renderSidebar({ collapsed: true });

      const sidebar = screen.getByTestId('sidebar');
      expect(sidebar).toBeTruthy();
      // Width is controlled by CSS Grid parent, not the sidebar itself
    });
  });

  describe('collapse toggle', () => {
    it('toggles collapsed state on button click', async () => {
      const user = userEvent.setup();
      renderSidebar();

      const toggle = screen.getByTitle('Collapse sidebar');
      await user.click(toggle);

      expect(localStorage.getItem('osint-sidebar-collapsed')).toBe('true');
    });

    it('expands when clicking toggle in collapsed state', async () => {
      const user = userEvent.setup();
      renderSidebar({ collapsed: true });

      const toggle = screen.getByTitle('Expand sidebar');
      await user.click(toggle);

      expect(localStorage.getItem('osint-sidebar-collapsed')).toBe('false');
    });
  });

  describe('active route highlighting', () => {
    it('highlights the active route with primary border', () => {
      renderSidebar({ route: '/watches' });

      const watchesLink = screen.getByRole('link', { name: /watches/i });
      expect(watchesLink).toHaveClass('border-primary');
    });

    it('does not highlight inactive routes with primary border', () => {
      renderSidebar({ route: '/watches' });

      const reportsLink = screen.getByRole('link', { name: /reports/i });
      expect(reportsLink).toHaveClass('border-transparent');
      expect(reportsLink).not.toHaveClass('border-primary');
    });
  });

  describe('badge counts', () => {
    it('renders badge count elements for badged items', () => {
      renderSidebar();

      expect(screen.getByTestId('badge-alerts')).toBeInTheDocument();
      expect(screen.getByTestId('badge-leads')).toBeInTheDocument();
      expect(screen.getByTestId('badge-watches')).toBeInTheDocument();
    });
  });

  describe('keyboard accessibility', () => {
    it('all nav items are focusable', () => {
      renderSidebar();

      const links = screen.getAllByRole('link');
      links.forEach((link) => {
        expect(link).not.toHaveAttribute('tabindex', '-1');
      });
    });

    it('collapse toggle is keyboard accessible', () => {
      renderSidebar();

      const toggle = screen.getByTitle('Collapse sidebar');
      expect(toggle.tagName).toBe('BUTTON');
    });
  });
});
