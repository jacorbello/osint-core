# Documentation Audit & Update — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring all osint-core documentation in sync with the current codebase — update stale docs, create missing docs, remove obsolete docs.

**Architecture:** 9 parallel agents, each owning a domain end-to-end. Each agent reads source code, reads existing docs (if any), and writes/updates their doc file. A final task reviews all output and commits.

**Tech Stack:** Markdown documentation, derived from Python source (FastAPI, SQLAlchemy, Celery, Pydantic)

---

## File Map

| File | Action | Owner |
|------|--------|-------|
| `docs/api-reference.md` | Create | Task 1 |
| `docs/connectors.md` | Create | Task 2 |
| `docs/architecture.md` | Create | Task 3 |
| `docs/data-model.md` | Create | Task 4 |
| `docs/bootstrap-plan.md` | Update | Task 5 |
| `docs/configuration.md` | Audit/Update | Task 6 |
| `docs/runbook.md` | Update | Task 7 |
| `docs/verification.md` | Update | Task 7 |
| `deploy/k8s/README.md` | Audit/Update | Task 8 |
| `docs/plans/*` | Evaluate for deletion | Task 9 |
| `docs/superpowers/specs/*` | Evaluate for deletion | Task 9 |
| `docs/superpowers/plans/*` | Evaluate for deletion | Task 9 |

## Conventions (all tasks)

- Each doc starts with a one-line purpose statement
- Reference actual code paths (e.g., `src/osint_core/api/routes/events.py`)
- Use tables for structured data (endpoints, env vars, connectors)
- No AI attribution (no Co-Authored-By, no Claude Code mentions)
- Factual — derived from current code state, not aspirational
- No emojis

---

### Task 1: API Reference — Create `docs/api-reference.md`

**Files:**
- Create: `docs/api-reference.md`
- Read: `src/osint_core/api/routes/alerts.py`
- Read: `src/osint_core/api/routes/audit.py`
- Read: `src/osint_core/api/routes/briefs.py`
- Read: `src/osint_core/api/routes/entities.py`
- Read: `src/osint_core/api/routes/events.py`
- Read: `src/osint_core/api/routes/health.py`
- Read: `src/osint_core/api/routes/indicators.py`
- Read: `src/osint_core/api/routes/ingest.py`
- Read: `src/osint_core/api/routes/jobs.py`
- Read: `src/osint_core/api/routes/leads.py`
- Read: `src/osint_core/api/routes/plan.py`
- Read: `src/osint_core/api/routes/preferences.py`
- Read: `src/osint_core/api/routes/search.py`
- Read: `src/osint_core/api/routes/watches.py`
- Read: `src/osint_core/api/deps.py`
- Read: `src/osint_core/api/errors.py`
- Read: `src/osint_core/api/middleware/auth.py`
- Read: `src/osint_core/api/middleware/rate_limit.py`
- Read: `src/osint_core/main.py` (for router registration and prefix)
- Read: `src/osint_core/schemas/*.py` (for request/response types)

- [ ] **Step 1: Read all route files**

Read every file listed above. For each route file, extract:
- All `@router.get/post/put/patch/delete` decorated functions
- The path, HTTP method, and function name
- Request body type (Pydantic schema) and response model
- Query parameters and path parameters
- Any dependency injections from `deps.py`

- [ ] **Step 2: Read middleware and error handling**

Read `auth.py`, `rate_limit.py`, `errors.py`, and `deps.py`. Note:
- How auth is enforced (Keycloak OIDC, `auth_disabled` bypass)
- Rate limiting behavior (per-IP, per-user)
- Standard error response format
- Common dependencies (DB session, current user, etc.)

- [ ] **Step 3: Write `docs/api-reference.md`**

Structure the doc as:

```markdown
# API Reference

All endpoints are served under the `/api/v1` prefix (configurable via `OSINT_API_PREFIX`).

## Authentication

[How auth works, how to disable for dev]

## Rate Limiting

[Per-IP and per-user limits]

## Error Responses

[Standard error format]

## Endpoints

### Health
| Method | Path | Description | Auth |
|--------|------|-------------|------|
| GET | /healthz | ... | No |

### Events
| Method | Path | Description | Auth |
...

[Continue for each router: Alerts, Audit, Briefs, Entities, Events, Health, Indicators, Ingest, Jobs, Leads, Plan, Preferences, Search, Watches]
```

For each endpoint, document: method, full path (with prefix), description, auth required (yes/no), request body schema name, response schema name, query/path params.

- [ ] **Step 4: Verify completeness**

Count the total endpoints in the doc. Grep all route files for decorator patterns to confirm no endpoints were missed:
```bash
grep -r "@router\." src/osint_core/api/routes/ | wc -l
```

Compare this count against the doc. Fix any gaps.

---

### Task 2: Connectors Reference — Create `docs/connectors.md`

**Files:**
- Create: `docs/connectors.md`
- Read: `src/osint_core/connectors/__init__.py`
- Read: `src/osint_core/connectors/base.py`
- Read: `src/osint_core/connectors/registry.py`
- Read: `src/osint_core/connectors/abusech.py`
- Read: `src/osint_core/connectors/acled.py`
- Read: `src/osint_core/connectors/cisa_kev.py`
- Read: `src/osint_core/connectors/gdelt.py`
- Read: `src/osint_core/connectors/nvd.py`
- Read: `src/osint_core/connectors/nws.py`
- Read: `src/osint_core/connectors/osv.py`
- Read: `src/osint_core/connectors/otx.py`
- Read: `src/osint_core/connectors/pastebin.py`
- Read: `src/osint_core/connectors/reddit.py`
- Read: `src/osint_core/connectors/reliefweb.py`
- Read: `src/osint_core/connectors/rss.py`
- Read: `src/osint_core/connectors/shodan.py`
- Read: `src/osint_core/connectors/telegram.py`
- Read: `src/osint_core/connectors/threatfox.py`
- Read: `src/osint_core/connectors/university_policy.py`
- Read: `src/osint_core/connectors/urlhaus.py`
- Read: `src/osint_core/connectors/xai_x_search.py`
- Read: `plans/*.yaml` (all 8 plan files)

- [ ] **Step 1: Read base connector and registry**

Read `base.py` to understand:
- `BaseConnector` interface (abstract methods, constructor signature)
- `SourceConfig` dataclass (fields available to connectors)
- `RawItem` structure (what connectors return)

Read `registry.py` to understand the registration mechanism.

Read `__init__.py` to get the full list of registered connectors and their source_type keys.

- [ ] **Step 2: Read all 18 connector implementations**

For each connector file, extract:
- Class name
- Source type key (from `__init__.py` registration)
- External data source URL/API
- What data it fetches (description)
- Any required environment variables or API keys
- Rate limiting or special configuration
- The `fetch()` method's behavior (pagination, lookback windows, etc.)

- [ ] **Step 3: Read plan YAML files**

Read all 8 files in `plans/`:
- `austin-terror-threat.yaml`
- `austin-terror-watch.yaml`
- `cal-prospecting.yaml`
- `cortech-osint-master.yaml`
- `cyber-threat-intel.yaml`
- `example.yaml`
- `humanitarian-intel.yaml`
- `military-intel.yaml`

For each plan, note which source_type keys it references.

- [ ] **Step 4: Write `docs/connectors.md`**

Structure the doc as:

```markdown
# Connectors Reference

Connectors fetch data from external OSINT sources. Each connector implements `BaseConnector` (defined in `src/osint_core/connectors/base.py`) and is registered in the `ConnectorRegistry` with a `source_type` key.

## Base Interface

[BaseConnector abstract methods, SourceConfig fields, RawItem structure]

## Registry

[How connectors are registered, how to add a new one]

## Connector Catalog

| source_type | Class | Data Source | Required Config |
|-------------|-------|-------------|----------------|
| cisa_kev | CisaKevConnector | CISA KEV | None |
| ... | ... | ... | ... |

### cisa_kev — CISA Known Exploited Vulnerabilities
**File:** `src/osint_core/connectors/cisa_kev.py`
[Description, data source URL, fetch behavior, config]

[Repeat for each of the 18 connectors]

## Plan Usage

| Plan | Sources |
|------|---------|
| cyber-threat-intel | cisa_kev, nvd_json_feed, ... |
| ... | ... |
```

- [ ] **Step 5: Verify completeness**

Confirm 18 connectors are documented by checking the count in `__init__.py`:
```bash
grep "registry.register" src/osint_core/connectors/__init__.py | wc -l
```

---

### Task 3: Architecture — Create `docs/architecture.md`

**Files:**
- Create: `docs/architecture.md`
- Read: `src/osint_core/main.py`
- Read: `src/osint_core/db.py`
- Read: `src/osint_core/logging.py`
- Read: `src/osint_core/metrics.py`
- Read: `src/osint_core/tracing.py`
- Read: `src/osint_core/workers/celery_app.py`
- Read: `src/osint_core/workers/ingest.py`
- Read: `src/osint_core/workers/enrich.py`
- Read: `src/osint_core/workers/nlp_enrich.py`
- Read: `src/osint_core/workers/score.py`
- Read: `src/osint_core/workers/notify.py`
- Read: `src/osint_core/workers/digest.py`
- Read: `src/osint_core/workers/prospecting.py`
- Read: `src/osint_core/workers/retention.py`
- Read: `src/osint_core/workers/k8s_dispatch.py`
- Read: `src/osint_core/services/scoring.py`
- Read: `src/osint_core/services/correlation.py`
- Read: `src/osint_core/services/dedup.py`
- Read: `src/osint_core/services/vectorize.py`
- Read: `src/osint_core/services/ner.py`
- Read: `src/osint_core/services/alerting.py`
- Read: `src/osint_core/services/alert_rules.py`
- Read: `src/osint_core/services/notification.py`
- Read: `src/osint_core/services/resend_notifier.py`
- Read: `src/osint_core/services/brief_generator.py`
- Read: `src/osint_core/services/indicators.py`
- Read: `src/osint_core/services/lead_matcher.py`
- Read: `src/osint_core/services/watch_matcher.py`
- Read: `src/osint_core/services/plan_engine.py`
- Read: `src/osint_core/services/plan_store.py`
- Read: `src/osint_core/services/prospecting_report.py`
- Read: `src/osint_core/services/pdf_export.py`
- Read: `src/osint_core/services/courtlistener.py`
- Read: `src/osint_core/services/geo.py`
- Read: `src/osint_core/services/audit.py`
- Read: `docker-compose.dev.yaml`

- [ ] **Step 1: Read infrastructure files**

Read `main.py`, `db.py`, `logging.py`, `metrics.py`, `tracing.py` to understand:
- How the FastAPI app is composed (routers, middleware, lifespan)
- Database session management (async SQLAlchemy)
- Logging configuration
- Prometheus metrics
- OpenTelemetry tracing setup

- [ ] **Step 2: Read all worker files**

Read `celery_app.py` and all 9 worker task files. For each worker, note:
- Celery task name(s)
- What it does
- What it calls downstream (task chains)
- Beat schedule (if any)

- [ ] **Step 3: Read all service files**

Read all 18 service files. For each service, note:
- Purpose (one sentence)
- Key functions/classes
- Dependencies (other services, external APIs, DB)

- [ ] **Step 4: Read docker-compose**

Read `docker-compose.dev.yaml` to understand the full service topology (API, worker, beat, Redis, Postgres, Qdrant, MinIO, etc.).

- [ ] **Step 5: Write `docs/architecture.md`**

Structure the doc as:

```markdown
# Architecture

OSINT-Core is an intelligence collection and analysis platform built on FastAPI (API layer), Celery (async task processing), PostgreSQL (persistence), Redis (broker/cache), and Qdrant (vector search).

## System Overview

[High-level description of the platform — what it does, who it serves]

## Service Topology

[List of services from docker-compose: api, worker, beat, postgres, redis, qdrant, minio]

## Request Flow

[How an API request is processed: middleware → route → service → DB]

## Ingest Pipeline

[The core data flow: trigger → ingest worker → connector → dedup → persist → chain (score, vectorize, correlate, notify)]

## Workers

| Worker | Celery Task | Purpose |
|--------|-------------|---------|
| ingest | osint.ingest_source | Fetches data via connectors |
| ... | ... | ... |

## Services

| Service | File | Purpose |
|---------|------|---------|
| Scoring | services/scoring.py | NLP-based event severity scoring |
| ... | ... | ... |

## Infrastructure

### Database
[Async SQLAlchemy with asyncpg, session management]

### Logging
[Structured JSON logging via structlog or similar]

### Metrics
[Prometheus metrics endpoint]

### Tracing
[OpenTelemetry integration]
```

---

### Task 4: Data Model — Create `docs/data-model.md`

**Files:**
- Create: `docs/data-model.md`
- Read: `src/osint_core/models/base.py`
- Read: `src/osint_core/models/event.py`
- Read: `src/osint_core/models/indicator.py`
- Read: `src/osint_core/models/entity.py`
- Read: `src/osint_core/models/alert.py`
- Read: `src/osint_core/models/artifact.py`
- Read: `src/osint_core/models/audit.py`
- Read: `src/osint_core/models/brief.py`
- Read: `src/osint_core/models/job.py`
- Read: `src/osint_core/models/lead.py`
- Read: `src/osint_core/models/plan.py`
- Read: `src/osint_core/models/report.py`
- Read: `src/osint_core/models/user_preference.py`
- Read: `src/osint_core/models/watch.py`
- Read: `src/osint_core/schemas/*.py` (all Pydantic schema files)

- [ ] **Step 1: Read base model**

Read `models/base.py` to understand the base class (shared columns like `id`, `created_at`, `updated_at`, etc.).

- [ ] **Step 2: Read all model files**

For each model file, extract:
- Table name
- All columns with types and constraints
- Relationships (foreign keys, back-references)
- Indexes
- Any enums or custom types

- [ ] **Step 3: Read all Pydantic schema files**

For each schema file, extract:
- Schema class names (Create, Read, Update, List variants)
- Fields and types
- Which model they correspond to

- [ ] **Step 4: Write `docs/data-model.md`**

Structure the doc as:

```markdown
# Data Model

All SQLAlchemy models inherit from a shared base (`src/osint_core/models/base.py`). The database uses PostgreSQL with async access via asyncpg.

## Base Model

[Common columns: id, created_at, updated_at, etc.]

## Models

### Event (`events` table)
**File:** `src/osint_core/models/event.py`

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| id | UUID | No | Primary key |
| ... | ... | ... | ... |

**Relationships:** [list FK relationships]

**Pydantic Schemas:** `EventCreate`, `EventRead`, `EventUpdate` (from `src/osint_core/schemas/event.py`)

[Repeat for each model: Event, Indicator, Entity, Alert, Artifact, Audit, Brief, Job, Lead, Plan/PlanVersion, Report, UserPreference, Watch]

## Entity Relationship Summary

[Text description of how models relate to each other — events have indicators, events belong to jobs, alerts reference events, etc.]
```

---

### Task 5: Bootstrap & Plans — Update `docs/bootstrap-plan.md`

**Files:**
- Modify: `docs/bootstrap-plan.md`
- Read: `plans/austin-terror-threat.yaml`
- Read: `plans/austin-terror-watch.yaml`
- Read: `plans/cal-prospecting.yaml`
- Read: `plans/cortech-osint-master.yaml`
- Read: `plans/cyber-threat-intel.yaml`
- Read: `plans/example.yaml`
- Read: `plans/humanitarian-intel.yaml`
- Read: `plans/military-intel.yaml`
- Read: `plans/templates/` (if exists)
- Read: `src/osint_core/api/routes/plan.py`
- Read: `src/osint_core/services/plan_engine.py`
- Read: `src/osint_core/services/plan_store.py`
- Read: `schemas/plan-v1.schema.json`
- Read: `scripts/load_plan.sh`

- [ ] **Step 1: Read current plan files**

Read all 8 YAML plan files and `plans/templates/` directory. For each plan extract:
- `plan_id`
- Description/purpose
- List of source_type keys it configures

- [ ] **Step 2: Read plan API routes and services**

Read `plan.py` routes, `plan_engine.py`, and `plan_store.py` to verify:
- All documented API endpoints still exist
- No new endpoints have been added
- The sync/activate flow is accurately described

- [ ] **Step 3: Read the plan schema and load script**

Read `schemas/plan-v1.schema.json` and `scripts/load_plan.sh` to verify documented behavior.

- [ ] **Step 4: Update `docs/bootstrap-plan.md`**

Update the existing doc with:
- **Plan files table:** Expand from 2 plans to all 8, with plan_id, description, and source count for each
- **Quick start:** Verify commands are still accurate
- **API reference table:** Verify all endpoints match the route file
- **Any new functionality** that's been added since the doc was written

The current doc says "Primary CTI plan — 6 connectors" for cyber-threat-intel. Update this and all similar references to match the actual YAML content.

---

### Task 6: Configuration — Audit `docs/configuration.md`

**Files:**
- Modify (if needed): `docs/configuration.md`
- Read: `src/osint_core/config.py`
- Read: `docs/configuration.md` (existing)

- [ ] **Step 1: Read config.py and existing doc**

Read `src/osint_core/config.py` and `docs/configuration.md` side by side.

- [ ] **Step 2: Diff fields**

For every field in the `Settings` class in `config.py`:
- Verify it appears in `configuration.md`
- Verify the default value matches
- Verify the description is accurate
- Verify the "Required" column is correct

Also check the reverse: are there any entries in the doc that no longer exist in `config.py`?

- [ ] **Step 3: Update if needed**

If any discrepancies are found, update `docs/configuration.md`. If the doc is fully accurate, report "no changes needed" and leave the file unchanged.

---

### Task 7: Runbook + Verification — Update `docs/runbook.md` and `docs/verification.md`

**Files:**
- Modify: `docs/runbook.md`
- Modify: `docs/verification.md`
- Read: `scripts/verify_ingest.sh`
- Read: `scripts/load_plan.sh`
- Read: `docker-compose.dev.yaml`
- Read: `src/osint_core/api/routes/health.py`
- Read: `src/osint_core/api/routes/ingest.py`
- Read: `src/osint_core/api/routes/jobs.py`
- Read: `.github/workflows/ci.yaml`

- [ ] **Step 1: Read existing docs and scripts**

Read both doc files and both scripts. Note every command, URL, plan_id, and source_id referenced.

- [ ] **Step 2: Read docker-compose and CI workflow**

Read `docker-compose.dev.yaml` to verify service names and commands. Read `ci.yaml` to verify the CI/CD migration section is accurate.

- [ ] **Step 3: Identify stale references**

Look for:
- `libertycenter-osint` plan ID (may need updating to `cyber-threat-intel` or making generic)
- Outdated source IDs
- Commands that reference services or endpoints that have changed
- CI/CD steps that no longer match the workflow file

- [ ] **Step 4: Update `docs/runbook.md`**

Fix all stale references. Verify:
- Quick reference table commands are accurate
- Common operations section matches current docker-compose service names
- CI/CD migration section matches `.github/workflows/ci.yaml`
- Job retry endpoint exists

- [ ] **Step 5: Update `docs/verification.md`**

Fix all stale references. Verify:
- Pipeline overview flow diagram is accurate (check worker chain)
- Default SOURCE_ID and PLAN_ID match what the script actually defaults to
- All endpoint paths are correct
- Troubleshooting section references are valid

---

### Task 8: Deployment — Audit `deploy/k8s/README.md`

**Files:**
- Modify (if needed): `deploy/k8s/README.md`
- Read: `deploy/k8s/README.md` (existing)
- Read: `deploy/k8s/migration-job.yaml`
- Read: `.github/workflows/ci.yaml`
- Read: `Dockerfile`

- [ ] **Step 1: Read existing doc and deployment files**

Read the README, migration job manifest, CI workflow, and Dockerfile.

- [ ] **Step 2: Verify accuracy**

Check:
- Image registry URL (harbor.corbello.io) is correct
- Migration job manifest structure matches what the README describes
- CI pipeline behavior matches the README description
- ArgoCD hook instructions are still valid
- The cortech-infra repo reference is accurate

- [ ] **Step 3: Update if needed**

If any discrepancies are found, update `deploy/k8s/README.md`. If accurate, report "no changes needed."

---

### Task 9: Old Docs Cleanup — Evaluate for Deletion

**Files:**
- Read: `docs/plans/2026-03-03-ingest-pipeline-wiring-design.md`
- Read: `docs/plans/2026-03-03-ingest-pipeline-implementation.md`
- Read: `docs/plans/2026-03-03-cicd-pipeline-implementation.md`
- Read: `docs/plans/2026-03-03-cicd-pipeline-design.md`
- Read: `docs/plans/2026-03-04-image-build-optimization-design.md`
- Read: `docs/plans/2026-03-04-image-build-optimization-implementation.md`
- Read: `docs/superpowers/plans/2026-03-16-platform-tuning.md`
- Read: `docs/superpowers/specs/2026-03-16-platform-tuning-design.md`
- Read: `docs/superpowers/specs/2026-03-16-alembic-ci-migrations-design.md`
- Read: `docs/superpowers/plans/2026-03-16-alembic-ci-migrations.md`
- Read: `docs/superpowers/plans/2026-03-16-nlp-scoring-schema-fixes.md`
- Read: `docs/superpowers/specs/2026-03-16-nlp-scoring-schema-fixes-design.md`
- Read: `docs/superpowers/specs/2026-03-26-ingest-stability-fixes-design.md`
- Read: `docs/superpowers/plans/2026-03-26-ingest-stability-fixes.md`
- Read: `docs/superpowers/plans/2026-03-26-xai-x-search-connector.md`
- Read: `docs/superpowers/specs/2026-03-26-xai-x-search-connector-design.md`
- Read: `docs/superpowers/specs/2026-03-27-cal-prospecting-design.md`
- Read: `docs/superpowers/specs/2026-03-30-documentation-audit-design.md`

- [ ] **Step 1: Read all old plan/spec docs**

Read every file listed above. For each file, determine:
- What work it describes
- Whether that work has been completed (is the code in the repo?)
- Whether any information in the doc is NOT captured elsewhere (new docs or code)

- [ ] **Step 2: Produce a deletion recommendation report**

Create a structured report (do NOT delete any files). Format:

```markdown
## Old Docs Cleanup Recommendations

### Recommend Delete
| File | Reason |
|------|--------|
| docs/plans/2026-03-03-... | Completed work, code is in repo, superseded by new architecture doc |

### Recommend Keep
| File | Reason |
|------|--------|
| docs/superpowers/specs/2026-03-30-... | Current work, still active |

### Notes
[Any files where the decision is ambiguous]
```

**Important:** Do NOT delete any files. Only produce the report. The user will decide what to delete.

---

### Task 10: Review and Commit

**Depends on:** Tasks 1-9 all complete

- [ ] **Step 1: Review all new/updated docs**

Read each doc produced by Tasks 1-8. Check for:
- Consistent formatting across all docs
- Cross-references between docs are correct (e.g., architecture doc references data model doc)
- No placeholder text left behind
- No AI attribution

- [ ] **Step 2: Review Task 9 cleanup report**

Present the cleanup recommendations to the user for approval.

- [ ] **Step 3: Commit all documentation changes**

```bash
git add docs/api-reference.md docs/connectors.md docs/architecture.md docs/data-model.md docs/bootstrap-plan.md docs/configuration.md docs/runbook.md docs/verification.md deploy/k8s/README.md
git commit -m "docs: comprehensive documentation audit and update"
```

- [ ] **Step 4: Delete approved old docs (if user approves)**

After user reviews the cleanup report from Task 9:
```bash
git rm <approved files>
git commit -m "docs: remove obsolete plan and spec documents"
```

- [ ] **Step 5: Create PR**

```bash
git push -u origin docs/documentation-audit
gh pr create --title "docs: comprehensive documentation audit and update" --body "..."
```
