# OSINT Platform Web UI

Production-ready React frontend for the OSINT monitoring platform, built with Vite, TypeScript, and Tailwind CSS.

## Tech Stack

- **Build Tool**: Vite 8
- **Framework**: React 18 with TypeScript
- **Styling**: Tailwind CSS with Material Design 3 tokens
- **UI Components**: Radix UI primitives
- **Routing**: React Router v6
- **Server State**: TanStack Query v5
- **Data Tables**: TanStack Table v8
- **Maps**: react-leaflet + Leaflet
- **HTTP Client**: axios
- **Utilities**: remeda, date-fns, clsx, tailwind-merge

## Design System

The UI follows Material Design 3 principles with a dark-mode-first approach:

- **Colors**: Cyan primary (#00E5FF), purple secondary (#bdc2ff), amber tertiary (#fec931)
- **Typography**: Space Grotesk (headlines), Inter (body/labels)
- **Border Radius**: Tight radii (0.125rem default, 0.75rem full)
- **Scrollbars**: Custom styled, 4px width

## Project Structure

```
src/
├── app/                    # App setup and providers
│   ├── App.tsx            # Root app component
│   ├── router.tsx         # React Router configuration
│   └── providers.tsx      # Query client provider
├── components/
│   ├── ui/                # Radix wrappers (Button, Input, Dialog, etc.)
│   ├── layout/            # AppShell, TopBar, SideNav
│   ├── data-display/      # KeyValueList, Badge, Timestamp, etc.
│   ├── feedback/          # EmptyState, ErrorBanner, Skeleton
│   ├── events/            # (Phase 2) Event-specific components
│   ├── plans/             # (Phase 3) Plan-specific components
│   ├── briefs/            # (Phase 3) Brief-specific components
│   └── maps/              # (Phase 4) Map visualization components
├── features/              # Feature-specific page components
│   ├── dashboard/         # (Phase 2)
│   ├── events/            # (Phase 2)
│   ├── plans/             # (Phase 3)
│   └── briefs/            # (Phase 3)
├── lib/
│   ├── api/               # Axios client + endpoint wrappers
│   ├── query/             # TanStack Query configuration
│   └── utils/             # cn(), formatters, mappers
├── types/
│   └── api/               # TypeScript types from backend schemas
├── index.css              # Tailwind directives + global styles
└── main.tsx               # Application entry point
```

## Development

### Prerequisites

- Node.js 18+ (project uses npm workspaces)
- Backend API running at `https://osint.corbello.io` (or configure `VITE_API_BASE_URL`)

### Install Dependencies

From the monorepo root:

```bash
npm install
```

Or from `apps/web/`:

```bash
npm install
```

### Start Dev Server

From the monorepo root:

```bash
make web-dev
# or
npm run web:dev
```

From `apps/web/`:

```bash
npm run dev
```

The dev server runs on `http://localhost:3000` with HMR enabled.

### Build for Production

From the monorepo root:

```bash
make web-build
# or
npm run web:build
```

From `apps/web/`:

```bash
npm run build
```

Output is written to `apps/web/dist/`.

### Preview Production Build

```bash
npm run web:preview
```

### Lint

```bash
npm run lint
```

### Test (Vitest)

From the monorepo root:

```bash
make web-test
# or
npm run web:test
```

From `apps/web/`:

```bash
npm run test
npm run test:watch
npm run test:coverage
```

### TDD-First Workflow (Required)

For all frontend behavior changes:
- start by writing or updating a failing test (`*.test.tsx` or `*.test.ts`)
- implement the minimum code to pass
- refactor while keeping tests green
- do not merge UI behavior changes without accompanying tests

## Component Conventions

### UI Primitives

All Radix UI components are wrapped in `src/components/ui/` with consistent styling:

- Accept `className` prop for composition
- Use `cn()` utility for class merging
- Follow Tailwind color tokens
- Support dark mode by default

Example:

```tsx
import { Button } from '@/components/ui/Button';

<Button variant="primary" size="md">
  Click me
</Button>
```

### Data Display

Components in `src/components/data-display/` handle common data presentation patterns:

```tsx
import { SeverityBadge } from '@/components/data-display/SeverityBadge';
import { Timestamp } from '@/components/data-display/Timestamp';
import { ScorePill } from '@/components/data-display/ScorePill';

<SeverityBadge severity="high" />
<Timestamp date={event.ingested_at} relative />
<ScorePill score={0.87} />
```

### Feedback Components

Components in `src/components/feedback/` handle loading, empty, and error states:

```tsx
import { EmptyState } from '@/components/feedback/EmptyState';
import { ErrorBanner } from '@/components/feedback/ErrorBanner';
import { SkeletonTable } from '@/components/feedback/SkeletonTable';

{isLoading && <SkeletonTable rows={5} columns={4} />}
{error && <ErrorBanner error={error} />}
{isEmpty && <EmptyState title="No events found" icon="inbox" />}
```

## API Integration

### Axios Client

The API client is configured in `src/lib/api/client.ts`:

```typescript
import { apiClient } from '@/lib/api/client';

const response = await apiClient.get('/api/v1/events');
```

Base URL: `https://osint.corbello.io`

### TanStack Query

Query client is configured in `src/lib/query/client.ts` with:

- 60-second stale time
- 1 retry on failure
- No refetch on window focus

Example hook:

```typescript
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/lib/api/client';

function useEvents() {
  return useQuery({
    queryKey: ['events'],
    queryFn: async () => {
      const { data } = await apiClient.get('/api/v1/events');
      return data;
    },
  });
}
```

## Type Safety

TypeScript types in `src/types/api/` match backend Pydantic schemas:

- `common.ts`: Page, ProblemDetails, Severity, StatusEnum
- `event.ts`: Event, EventList, EventResponse
- `alert.ts`: Alert, AlertResponse, AlertStatus
- `brief.ts`: Brief, BriefResponse, BriefCreateRequest
- `plan.ts`: PlanVersion, PlanValidationResult
- `ui.ts`: DashboardSummary, FacetsResponse

## Routing

Routes are defined in `src/app/router.tsx`:

- `/` → redirects to `/dashboard`
- `/dashboard` → Dashboard (Phase 2)
- `/events` → Events Explorer (Phase 2)
- `/events/:eventId` → Event Detail (Phase 2)
- `/plans` → Plans Workspace (Phase 3)
- `/briefs` → Briefs Library (Phase 3)
- `/briefs/:briefId` → Brief Detail (Phase 3)

## Utilities

### Class Name Merging

```typescript
import { cn } from '@/lib/utils/cn';

<div className={cn('base-class', isActive && 'active-class', className)} />
```

### Formatters

```typescript
import { formatTimestamp, formatRelativeTime, formatScore } from '@/lib/utils/format';

formatTimestamp('2026-04-07T12:00:00Z'); // "Apr 7, 2026 12:00:00"
formatRelativeTime('2026-04-07T12:00:00Z'); // "2 hours ago"
formatScore(0.8734); // "0.87"
```

### Severity/Status Mappers

```typescript
import { getSeverityColor } from '@/lib/utils/severity';
import { getAlertStatusColor } from '@/lib/utils/status';

getSeverityColor('critical'); // "bg-error text-on-error"
getAlertStatusColor('open'); // "bg-error-container text-on-error-container"
```

## Phase Roadmap

### Phase 1: Foundation (Current)
✅ App shell with navigation  
✅ Design tokens and Tailwind config  
✅ Core UI primitives (Button, Input, Dialog, etc.)  
✅ Data display components (Badge, Timestamp, etc.)  
✅ Feedback components (EmptyState, ErrorBanner, etc.)  
✅ API and Query client setup  
✅ TypeScript types for core schemas  

### Phase 2: Dashboard + Events
- Dashboard with summary cards
- Events Explorer with table + facets + filters
- Event detail drawer with related records
- TanStack Table integration

### Phase 3: Plans + Briefs
- Plans workspace with YAML editor
- Plan validation and version controls
- Briefs library and reader
- PDF export

### Phase 4: Advanced Features
- Map visualization with react-leaflet
- Realtime SSE stream integration
- Bulk actions and export
- Preferences and saved searches

## Contributing

- Follow existing component patterns
- Use TypeScript strict mode
- Maintain dark-mode-first design
- Keep components composable and reusable
- Add types for all API responses

## License

MIT
