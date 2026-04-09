import { screen } from '@testing-library/react';
import { Route, Routes } from 'react-router-dom';
import { AppShell } from '@/components/layout/AppShell';
import { renderWithRouterAndProviders } from '@/test/renderWithProviders';

describe('AppShell', () => {
  it('renders shell chrome and route content for dashboard', () => {
    renderWithRouterAndProviders(
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route path="dashboard" element={<h1>Dashboard test page</h1>} />
        </Route>
      </Routes>,
      {
      router: { initialEntries: ['/dashboard'] },
      }
    );

    expect(screen.getByText('SENTINEL NODE')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Dashboard test page' })).toBeInTheDocument();
  });

  it('renders sidebar with intelligence cycle navigation', () => {
    renderWithRouterAndProviders(
      <Routes>
        <Route path="/" element={<AppShell />}>
          <Route path="dashboard" element={<div>content</div>} />
        </Route>
      </Routes>,
      {
      router: { initialEntries: ['/dashboard'] },
      }
    );

    expect(screen.getByText('OSINT Core')).toBeInTheDocument();
    expect(screen.getByText('COLLECT')).toBeInTheDocument();
    expect(screen.getByText('ANALYZE')).toBeInTheDocument();
    expect(screen.getByText('PRODUCE')).toBeInTheDocument();
  });
});
