import { createBrowserRouter } from 'react-router-dom';
import { AppShell } from '@/components/layout/AppShell';
import { OverviewPage } from '@/features/dashboard/components/OverviewPage';
import { WatchesPage } from '@/features/watches/components/WatchesPage';
import { AlertsPage } from '@/features/alerts/components/AlertsPage';
import { LeadsPage } from '@/features/leads/components/LeadsPage';
import { IntelligenceMapPage } from '@/features/map/components/IntelligenceMapPage';
import { PlaceholderPage } from '@/components/feedback/PlaceholderPage';

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      {
        index: true,
        element: <OverviewPage />,
      },
      {
        path: 'watches',
        element: <WatchesPage />,
      },
      {
        path: 'sources',
        element: (
          <PlaceholderPage
            icon="source"
            title="Sources"
            description="Source management coming soon"
            phase="Collection"
          />
        ),
      },
      {
        path: 'alerts',
        element: <AlertsPage />,
      },
      {
        path: 'investigations/:id',
        element: (
          <PlaceholderPage
            icon="search_insights"
            title="Investigations"
            description="Investigation workspace coming soon"
            phase="Analysis"
          />
        ),
      },
      {
        path: 'entities/:id',
        element: (
          <PlaceholderPage
            icon="hub"
            title="Entities"
            description="Entity resolution coming soon"
            phase="Analysis"
          />
        ),
      },
      {
        path: 'leads',
        element: <LeadsPage />,
      },
      {
        path: 'reports',
        element: (
          <PlaceholderPage
            icon="summarize"
            title="Reports"
            description="Report generation coming soon"
            phase="Production"
          />
        ),
      },
      {
        path: 'exports',
        element: (
          <PlaceholderPage
            icon="download"
            title="Exports"
            description="Data export coming soon"
            phase="Production"
          />
        ),
      },
      {
        path: 'map',
        element: <IntelligenceMapPage />,
      },
      {
        path: 'settings',
        element: (
          <PlaceholderPage
            icon="settings"
            title="Settings"
            description="Platform settings coming soon"
          />
        ),
      },
    ],
  },
]);
