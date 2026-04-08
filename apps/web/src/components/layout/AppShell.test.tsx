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
});
