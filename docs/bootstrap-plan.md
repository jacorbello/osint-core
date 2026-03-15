# Bootstrapping a Plan

Before any ingest tasks can run, an intelligence collection plan must be loaded
into the database and marked **active**.  Without an active plan the
`ingest_source` Celery task will fail with `No active plan`.

## Quick start

```bash
# 1. Start services
docker compose -f docker-compose.dev.yaml up -d

# 2. Run migrations (creates the plan_versions table, etc.)
docker compose exec api alembic upgrade head

# 3. Load and activate plans
./scripts/load_plan.sh              # uses http://localhost:8000 by default
./scripts/load_plan.sh http://api:8000  # or pass a custom API URL
```

The script calls `POST /api/v1/plan/sync`, which:

1. Scans `settings.plan_dir` (`/app/plans` inside the container) for `*.yaml` files.
2. Validates each file against the plan JSON Schema.
3. Stores a new `PlanVersion` row if the content hash has changed.
4. **Auto-activates** the newly stored version.

After sync the script verifies the `cyber-threat-intel` plan is active.

## Plan files

| File | plan_id | Description |
|------|---------|-------------|
| `plans/cyber-threat-intel.yaml` | `cyber-threat-intel` | Primary CTI plan — 6 connectors (CISA KEV, NVD, OSV/PyPI, URLhaus, ThreatFox, RSS/Hacker News) |
| `plans/example.yaml` | `libertycenter-osint` | Example/reference plan |

## Plan API reference

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/api/v1/plan/sync` | Load plans from disk, validate, store, and activate |
| `GET`  | `/api/v1/plan/active?plan_id=<id>` | Get the currently active plan version |
| `POST` | `/api/v1/plan/activate/{version_id}` | Activate a specific version by UUID |
| `POST` | `/api/v1/plan/rollback?plan_id=<id>` | Roll back to the previous version |
| `GET`  | `/api/v1/plan/versions?plan_id=<id>` | List all stored versions |
| `POST` | `/api/v1/plan/validate` | Validate a plan YAML (body) without persisting |

## Triggering an ingest manually

Once a plan is active you can trigger a single source:

```bash
curl -X POST "http://localhost:8000/api/v1/ingest/source/cisa_kev/run?plan_id=cyber-threat-intel"
```

## Updating a plan

Edit the YAML file and re-run `./scripts/load_plan.sh`.  A new version is
created only if the content hash differs from the latest stored version.  The
new version is auto-activated on sync.
