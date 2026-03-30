# Documentation Audit & Update — Design Spec

**Date:** 2026-03-30
**Goal:** Bring all documentation in sync with the current codebase state. Update stale docs, create missing docs, remove obsolete docs.

## Approach

Parallel write agents (9 agents), each owning a domain end-to-end. Each agent reads source code, reads existing docs (if any), and writes the updated/new doc file directly. Results reviewed and committed after all agents complete.

## Documentation Structure

```
docs/
├── api-reference.md          # NEW — all API endpoints by router
├── connectors.md             # NEW — all 18 connectors, config, source types
├── architecture.md           # NEW — services, workers, data flow
├── data-model.md             # NEW — SQLAlchemy models & relationships
├── bootstrap-plan.md         # UPDATED — fix stale plan/connector counts
├── configuration.md          # AUDITED — verify against config.py
├── runbook.md                # UPDATED — fix stale references
├── verification.md           # UPDATED — fix stale plan IDs
└── deploy/
    └── k8s/README.md         # AUDITED
```

Old docs evaluated for removal:
- `docs/plans/` — 6 files from March 3-4 (early design/implementation docs)
- `docs/superpowers/specs/` and `docs/superpowers/plans/` — completed work specs

## Agent Assignments

### Agent 1 — API Reference (`docs/api-reference.md`)
- Read all 13 route files in `src/osint_core/api/routes/`
- Read `api/deps.py`, `api/errors.py`, middleware files
- Document every endpoint: method, path, purpose, request/response schemas, auth requirements

### Agent 2 — Connectors Reference (`docs/connectors.md`)
- Read all 18 connector files + `registry.py` + `base.py`
- Read plan YAML files to show which plans use which connectors
- Document: source_type key, connector class, data source, config options, rate limits

### Agent 3 — Architecture (`docs/architecture.md`)
- Read all services (`services/`) and workers (`workers/`)
- Read `main.py`, `db.py`, `logging.py`, `metrics.py`, `tracing.py`
- Document: system overview, request flow, ingest pipeline, worker chain, service responsibilities

### Agent 4 — Data Model (`docs/data-model.md`)
- Read all models (`models/`) and schemas (`schemas/`)
- Document: tables, columns, relationships, Pydantic schemas

### Agent 5 — Bootstrap & Plans (update `docs/bootstrap-plan.md`)
- Read current plan files (8 YAMLs, not the 2 currently documented)
- Read plan routes and plan engine service
- Update the doc to reflect all current plans and connectors

### Agent 6 — Configuration (audit `docs/configuration.md`)
- Read `config.py` and diff against existing doc
- Verify every field is documented, defaults are correct, no missing vars

### Agent 7 — Runbook + Verification (update `docs/runbook.md` and `docs/verification.md`)
- Read current scripts, worker configs, docker-compose
- Fix stale plan IDs, update commands

### Agent 8 — Deployment (audit `deploy/k8s/README.md`)
- Read K8s manifests, CI/CD workflow files, Dockerfile
- Verify doc matches current deployment setup

### Agent 9 — Old Docs Cleanup
- Read each file in `docs/plans/` and `docs/superpowers/`
- Determine if content is superseded by code or other docs
- Produce a recommendation list of files to delete

## Conventions

- Each doc is self-contained with a clear purpose at the top
- Reference actual code paths (e.g., `src/osint_core/api/routes/events.py`)
- Tables for structured data (endpoints, env vars, connectors)
- No AI attribution
- Factual — derived from current code state, not aspirational
