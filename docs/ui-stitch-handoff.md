# OSINT UI + Stitch Handoff (New Session)

## Goal
In a new session, design the OSINT platform UI from current API contracts, then use Google Stitch to create a new project, establish a design system, and generate screens one at a time.

This handoff is implementation-oriented: the next session should not need to rediscover architecture decisions.

## Current API Surface To Use
Use the backend contracts from `src/osint_core/api/routes/` and `src/osint_core/schemas/` as source of truth.

### Core resource endpoints
- Events
  - `GET /api/v1/events`
  - `GET /api/v1/events/{event_id}`
  - `GET /api/v1/events/facets`
  - `GET /api/v1/events/export?format=csv|json`
  - `GET /api/v1/events/{event_id}/related?include=alerts,entities,indicators`
- Alerts
  - `GET /api/v1/alerts`
  - `GET /api/v1/alerts/{alert_id}`
  - `PATCH /api/v1/alerts/{alert_id}`
  - `GET /api/v1/alerts/facets`
  - `GET /api/v1/alerts/export?format=csv|json`
  - `POST /api/v1/alerts/bulk-update`
- Leads
  - `GET /api/v1/leads`
  - `GET /api/v1/leads/{lead_id}`
  - `PATCH /api/v1/leads/{lead_id}`
  - `GET /api/v1/leads/facets`
  - `GET /api/v1/leads/export?format=csv|json`
  - `POST /api/v1/leads/bulk-update`
- Watches
  - `GET /api/v1/watches`
  - `POST /api/v1/watches`
  - `GET /api/v1/watches/{watch_id}`
  - `PATCH /api/v1/watches/{watch_id}`
  - `DELETE /api/v1/watches/{watch_id}`
- Search
  - `GET /api/v1/search/events`
  - `GET /api/v1/search/events:semantic`
- Briefs
  - `GET /api/v1/briefs`
  - `POST /api/v1/briefs`
  - `GET /api/v1/briefs/{brief_id}`
  - `GET /api/v1/briefs/{brief_id}/pdf`
- Jobs
  - `GET /api/v1/jobs`
  - `POST /api/v1/jobs`
  - `GET /api/v1/jobs/{job_id}`
- Plans
  - `GET /api/v1/plans`
  - `POST /api/v1/plans:validate`
  - `POST /api/v1/plans`
  - `GET /api/v1/plans/{plan_id}/versions`
  - `GET /api/v1/plans/{plan_id}/versions/{version_id}`
  - `GET /api/v1/plans/{plan_id}/active-version`
  - `PATCH /api/v1/plans/{plan_id}/active-version`
- Preferences
  - `GET /api/v1/preferences`
  - `PUT /api/v1/preferences`
  - `GET /api/v1/saved-searches`
  - `POST /api/v1/saved-searches`
  - `DELETE /api/v1/saved-searches/{search_id}`
- System/UI support
  - `GET /api/v1/me`
  - `GET /api/v1/dashboard/summary`
  - `GET /api/v1/stream` (SSE)
  - `GET /api/v1/entities`, `GET /api/v1/entities/{entity_id}`
  - `GET /api/v1/indicators`, `GET /api/v1/indicators/{indicator_id}`
  - `GET /api/v1/audit`

### Important data types / UX constraints
- Shared enums
  - Severity: `info|low|medium|high|critical`
  - Alert status: `open|acked|escalated|resolved`
  - Job status: `queued|running|succeeded|failed|partial_success|dead_letter`
- Lead lifecycle
  - `new -> reviewing -> qualified -> contacted -> retained`
  - `declined` and `stale` branches with restricted transitions
- Bulk update request guardrail
  - `ids` max length `1000`
- Bulk response shape
  - `summary`, `updated[]`, `skipped[]`, `errors[]`
  - stable reason codes: `not_found|already_in_target|invalid_transition|update_failed`
- Export
  - `format=csv|json`, capped `limit` (max 5000)
- Pagination
  - `page: { offset, limit, total, has_more }`
- Error shape
  - RFC7807-like `ProblemDetails`
- Realtime
  - SSE event topics: `alert.updated`, `lead.updated`, `job.updated`

## Screen Plan (One-at-a-Time Build Order)
Design and generate screens in this order to minimize dependency churn:

1. **Global App Shell**
- Left nav + top bar + global search entry
- Realtime indicator + user/profile status (`/me`)

2. **Dashboard Home**
- KPI cards from `/dashboard/summary`
- Quick links to Alerts, Leads, Jobs, Events

3. **Events Explorer**
- Table/list + facets sidebar + sort + date filters
- Row click opens Event detail drawer seed state

4. **Event Detail + Related Drawer**
- Event core fields
- Related tabs: Alerts / Entities / Indicators from `/events/{id}/related`

5. **Alerts Triage**
- Queue view + single update + bulk update + export actions

6. **Leads Pipeline**
- Kanban/list hybrid + transition actions + bulk + export

7. **Watches Management**
- List + create/edit/delete with severity/geo/keywords

8. **Search Workbench**
- Lexical vs semantic mode toggle with shared result card component

9. **Jobs Monitor**
- Async job table + status chips + detail panel

10. **Plans Workspace**
- Validate YAML, version list, activate/rollback controls

11. **Briefs Library + Reader**
- Brief list + detail + open PDF action

12. **Preferences / Saved Searches**
- Notification prefs, timezone, saved search CRUD

13. **Audit Timeline (Admin/ops view)**
- Filterable action trail

## Stitch Execution Playbook (Next Session)
Use Stitch tools in this sequence:

1. **Create project**
- Call `create_project` with title like `OSINT Platform UI`.

2. **Create design system**
- Call `create_design_system` with explicit design language (palette, typography, corner style, interaction tone).
- Immediately call `update_design_system` for the created design system and project.

3. **Generate first screen**
- Call `generate_screen_from_text` with `projectId` and prompt for App Shell or Dashboard.

4. **Iterate screen-by-screen**
- Use `generate_screen_from_text` for net-new screens.
- Use `edit_screens` for refinements on selected screen ids.
- Apply design system to each accepted screen set via `apply_design_system`.

5. **Keep strict one-screen-at-a-time cadence**
- For each screen:
  - define purpose + endpoint dependencies
  - generate
  - refine
  - lock
  - move to next

## Prompt Template For Each Screen (Use in New Session)
Use this template when calling Stitch generation/edit tools:

"Design screen: <SCREEN_NAME>. Context: OSINT monitoring platform for homelab operators. Primary tasks: <TASKS>. Data contracts: <ENDPOINTS + KEY FIELDS>. Required states: loading, empty, success, error. Include actions: <ACTIONS>. Keep visual language consistent with existing design system. Prioritize readability and dense operational workflows over marketing aesthetics."

## Session Kickoff Script (Copy/Paste)
Use this text to start the next session:

1. Read current API route and schema contracts from:
- `src/osint_core/api/routes/`
- `src/osint_core/schemas/`
- `docs/ui-stitch-handoff.md`

2. Produce a compact screen IA (information architecture) using the build order in this doc.

3. Use Google Stitch to:
- create a new project for OSINT platform UI,
- create/update and apply a design system,
- then generate the first screen only.

4. After each screen, summarize:
- what was generated,
- what endpoint/data types it depends on,
- what to build next.

## Notes / Non-goals
- No auth UX required for now (homelab/private network).
- Do not redesign API contracts in design sessions.
- Keep endpoint-driven UX fidelity high; avoid placeholder-only flows without mapped API actions.
