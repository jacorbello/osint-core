import { createBrowserRouter, Navigate } from 'react-router-dom';
import { AppShell } from '@/components/layout/AppShell';
import { DashboardPage } from '@/features/dashboard/components/DashboardPage';

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { 
        index: true, 
        element: <Navigate to="/dashboard" replace /> 
      },
      { 
        path: 'dashboard', 
        element: <DashboardPage />
      },
      { 
        path: 'events', 
        element: (
          <div className="p-8">
            <h1 className="text-2xl font-headline text-primary-container">Events Explorer</h1>
            <p className="mt-4 text-on-surface-variant">Events page coming in Phase 2</p>
          </div>
        )
      },
      { 
        path: 'events/:eventId', 
        element: (
          <div className="p-8">
            <h1 className="text-2xl font-headline text-primary-container">Event Detail</h1>
            <p className="mt-4 text-on-surface-variant">Event detail page coming in Phase 2</p>
          </div>
        )
      },
      { 
        path: 'plans', 
        element: (
          <div className="p-8">
            <h1 className="text-2xl font-headline text-primary-container">Plans Workspace</h1>
            <p className="mt-4 text-on-surface-variant">Plans page coming in Phase 3</p>
          </div>
        )
      },
      { 
        path: 'briefs', 
        element: (
          <div className="p-8">
            <h1 className="text-2xl font-headline text-primary-container">Briefs Library</h1>
            <p className="mt-4 text-on-surface-variant">Briefs page coming in Phase 3</p>
          </div>
        )
      },
      { 
        path: 'briefs/:briefId', 
        element: (
          <div className="p-8">
            <h1 className="text-2xl font-headline text-primary-container">Brief Detail</h1>
            <p className="mt-4 text-on-surface-variant">Brief detail page coming in Phase 3</p>
          </div>
        )
      },
    ],
  },
]);
