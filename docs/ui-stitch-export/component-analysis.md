# UI Component Analysis

## Scope
This folder contains the exported Stitch artifacts for the current OSINT UI direction:

- `html/consolidated-osint-dashboard-active-map.html`
- `html/events-explorer-contract-accurate.html`
- `html/event-detail-investigation.html`
- `html/plans-workspace-activation-ops-console.html`
- `html/plans-workspace-validation-diff.html`
- `html/briefs-document-centric-split-view.html`

The goal of this document is to translate those screen exports into a practical frontend implementation plan for:

- Vite
- React
- TanStack Query + TanStack Table
- Axios
- Tailwind CSS
- Radix UI

The screens are enough to lock down the reusable primitives, domain components, and user-flow patterns. Preferences and saved searches can be extrapolated from the same system.

## Product Framing
The frontend should not be built as a narrow cyber/SOC dashboard. The reusable system needs to support broad OSINT workflows:

- event monitoring across public-source domains
- map-based situational awareness
- event investigation with linked records
- plan authoring, validation, activation, and rollback
- document-oriented brief generation and reading

That means the component model should prefer generalized intelligence concepts over cyber-specific naming. Examples:

- use `RecordSeverityBadge`, not `ThreatBadge`
- use `RelatedRecordsPanel`, not `IOCPanel`
- use `PlanNodeTypeCard`, not `PipelineStepCard`

## Recommended App Structure
Recommended top-level route structure:

- `/dashboard`
- `/events`
- `/events/:eventId`
- `/plans`
- `/briefs`
- `/briefs/:briefId`

Recommended source layout:

- `src/app`
- `src/components/ui`
- `src/components/layout`
- `src/components/data-display`
- `src/components/feedback`
- `src/components/events`
- `src/components/plans`
- `src/components/briefs`
- `src/components/maps`
- `src/features/dashboard`
- `src/features/events`
- `src/features/plans`
- `src/features/briefs`
- `src/lib/api`
- `src/lib/query`
- `src/lib/utils`
- `src/types/api`

## Component Inventory
### 1. Layout primitives
These should be built first because every finished screen depends on them.

- `AppShell`
- `AppRailNav`
- `TopUtilityBar`
- `PageHeader`
- `WorkspaceLayout`
- `SplitPaneLayout`
- `ThreePaneLayout`
- `RightDrawer`
- `MetadataRail`
- `ScrollablePanel`
- `SectionCard`
- `SectionHeader`

### 2. Core UI primitives
These should wrap Radix and establish the visual system once.

- `Button`
- `IconButton`
- `Input`
- `SearchInput`
- `Textarea`
- `Select`
- `Popover`
- `DropdownMenu`
- `Dialog`
- `Tabs`
- `Tooltip`
- `Checkbox`
- `Switch`
- `Badge`
- `Separator`
- `ScrollArea`
- `Table`
- `PaginationControls`
- `DateRangePicker`
- `CommandPalette`

### 3. Feedback and async-state primitives
These are shared across all screens because every API surface has loading, empty, and ProblemDetails-style failure states.

- `SkeletonBlock`
- `SkeletonTable`
- `EmptyState`
- `InlineEmptyState`
- `ErrorBanner`
- `ProblemDetailsAlert`
- `SuccessBanner`
- `WarningCallout`
- `ProgressState`
- `StreamingStatusIndicator`

### 4. Data-display primitives
These normalize the visual language of records across pages.

- `KeyValueList`
- `MetadataList`
- `Timestamp`
- `CopyableId`
- `ScorePill`
- `CountBadge`
- `DeltaBadge`
- `StatusBadge`
- `SeverityBadge`
- `RetentionClassBadge`
- `ModelBadge`
- `SourceChip`
- `RecordLinkChip`
- `SummaryBlock`
- `ExcerptBlock`
- `MarkdownRenderer`

### 5. Table and filter system
The dashboard, events explorer, and plans history all need a coherent data-grid pattern. Build this as a reusable system on top of TanStack Table.

- `DataTable`
- `DataTableToolbar`
- `ColumnVisibilityMenu`
- `DensityToggle`
- `SortMenu`
- `FacetSidebar`
- `FacetSection`
- `FacetOptionRow`
- `FilterChipBar`
- `BulkSelectionBar`
- `TablePaginationFooter`

### 6. Domain components for events
These cover the Events Explorer and Event Detail screens.

- `EventRow`
- `EventTable`
- `EventPreviewDrawer`
- `EventHeader`
- `EventSummaryPanel`
- `EventEvidencePanel`
- `EventLocationPanel`
- `EventMetadataPanel`
- `RelatedRecordsTabs`
- `AlertListMiniTable`
- `EntityListMiniTable`
- `IndicatorListMiniTable`

### 7. Domain components for dashboard
The map dashboard should be assembled from reusable operational widgets, not one-off page code.

- `SummaryStrip`
- `SummaryMetricCard`
- `RealtimeActivityRail`
- `OperationalMapPanel`
- `MapLegend`
- `MapControls`
- `MapTooltipCard`
- `SelectedNodePanel`
- `MetricStackCard`
- `CompactFeedCard`

### 8. Domain components for plans
This is the most specialized area and should be broken into reusable subcomponents instead of one monolithic workspace.

- `PlansList`
- `PlanListItem`
- `PlanWorkspaceHeader`
- `PlanYamlEditor`
- `PlanValidationPanel`
- `PlanValidationSummary`
- `PlanErrorList`
- `PlanWarningList`
- `PlanMetadataCard`
- `PlanVersionTimeline`
- `PlanVersionItem`
- `PlanActivationPanel`
- `PlanDiffViewer`
- `PlanComparePanel`
- `PlanNodePalette`
- `PlanNodeTypeCard`
- `PlanComposerCanvas`
- `PlanComposerNode`
- `InsertNodeMenu`

### 9. Domain components for briefs
These are document-oriented and should not be forced into the same interaction model as tables.

- `BriefsList`
- `BriefListItem`
- `BriefReaderHeader`
- `BriefReader`
- `BriefMetadataRail`
- `BriefLinkedRecordsPanel`
- `CreateBriefDialog`
- `BriefGenerationState`
- `ExportPdfButton`

## API Hook Inventory
Axios should stay thin. Put endpoint wrappers in `src/lib/api`, then wrap those with TanStack Query hooks.

### Shared query patterns
- `usePagedResource`
- `useProblemDetailsMutation`
- `useExportAction`

### Dashboard
- `useDashboardSummary`
- `useStreamEvents`

### Events
- `useEvents`
- `useEventFacets`
- `useEvent`
- `useEventRelated`
- `useExportEvents`

### Plans
- `usePlans`
- `usePlanVersions`
- `usePlanVersion`
- `useActivePlanVersion`
- `useValidatePlan`
- `useCreatePlanVersion`
- `useActivatePlanVersion`
- `useRollbackPlanVersion`

### Briefs
- `useBriefs`
- `useBrief`
- `useCreateBrief`
- `useBriefPdf`

## Shared UI Patterns
### Pattern: List + detail workspace
Used by events, briefs, and plans.

- left side for navigation, filtering, or record selection
- center as the primary working surface
- right side for metadata, actions, or related records

Build a common layout contract for this instead of hardcoding widths page-by-page.

### Pattern: Explicit operational states
Each feature needs consistent handling for:

- initial loading
- partial loading
- empty result
- validation failure
- dependency failure
- stale or in-progress operations

ProblemDetails handling should be standardized so every screen renders `code` and `detail` consistently.

### Pattern: Dense metadata presentation
These screens rely on small, scannable metadata groups. Reuse:

- label/value rows
- compact badges
- inline timestamps
- linked record count chips

### Pattern: Safe action rails
Plans and briefs both need action clusters that are explicit and low-ambiguity:

- primary action
- secondary action
- destructive or high-risk action
- status summary above actions

### Pattern: Markdown plus structured context
Briefs use markdown as the main body, but still need structured metadata on the side. Keep the reader layout reusable for any future narrative intelligence views.

## User Flows To Support
### 1. Dashboard to event investigation

1. Open dashboard.
2. Inspect map or activity rail.
3. Jump into events explorer or a selected event.
4. Open event detail.
5. Traverse related alerts, entities, indicators.

### 2. Event triage flow

1. Search or filter events.
2. Sort by severity, score, or recency.
3. Open drawer.
4. Compare evidence and summary.
5. Follow linked records.

### 3. Plan authoring and activation flow

1. Select plan.
2. Edit YAML or insert typed nodes.
3. Validate.
4. Review warnings or diff.
5. Create version.
6. Activate or roll back.

### 4. Brief generation and reading flow

1. Enter query.
2. Generate brief.
3. Monitor in-progress state.
4. Read markdown output.
5. Export PDF.
6. Traverse linked records if needed.

## Implementation Order
### Phase 1: foundation

- App shell
- design tokens
- buttons, inputs, tabs, badges
- async-state components
- table system

### Phase 2: shared composites

- list/detail layouts
- metadata cards
- filter sidebar
- pagination
- markdown reader

### Phase 3: feature modules

- dashboard widgets and map shell
- events explorer and detail
- plans workspace and version controls
- briefs library and reader

### Phase 4: advanced plan tooling

- typed node palette
- visual composer canvas
- diff viewer
- activation safety workflows

## Tailwind and Radix Guidance
Tailwind should carry layout, spacing, tokens, and state styling. Radix should be used for behavioral primitives:

- Dialog
- Dropdown Menu
- Popover
- Tabs
- Tooltip
- Scroll Area
- Select

Do not build feature components directly out of raw Radix every time. Wrap them once in `src/components/ui` and keep feature code declarative.

## TanStack Guidance
Use TanStack Query for server state and TanStack Table for dense data views.

Preferred conventions:

- query keys grouped by feature and params
- server pagination modeled explicitly from `offset`, `limit`, `total`, `has_more`
- mutations invalidate narrowly, not globally
- tables keep column definitions near feature components but reuse base cell renderers

## Recommended Next Deliverables
The next implementation documents that should be created after this file:

1. `docs/ui-stitch-export/component-architecture.md`
2. `docs/ui-stitch-export/page-to-component-mapping.md`
3. `docs/ui-stitch-export/user-flows.md`
4. `docs/ui-stitch-export/frontend-build-order.md`

If you want to move straight into code, the highest-leverage first step is to scaffold the app shell, async-state primitives, badge system, and reusable data table before building any feature page.
