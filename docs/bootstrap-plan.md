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

# In production (auth_disabled=false), pass a Bearer token:
# OSINT_API_TOKEN=<token> ./scripts/load_plan.sh http://api:8000
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
| `plans/cyber-threat-intel.yaml` | `cyber-threat-intel` | Primary CTI plan — 9 connectors (CISA KEV, NVD, OSV/PyPI, URLhaus, ThreatFox, The Hacker News, OTX, MalwareBazaar, FeodoTracker) |
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
# With auth disabled (OSINT_AUTH_DISABLED=true, e.g. in dev):
curl -X POST "http://localhost:8000/api/v1/ingest/source/cisa_kev/run?plan_id=cyber-threat-intel"

# With auth enabled, include a Bearer token:
curl -X POST "http://localhost:8000/api/v1/ingest/source/cisa_kev/run?plan_id=cyber-threat-intel" \
  -H "Authorization: Bearer <token>"
```

## Updating a plan

Edit the YAML file and re-run `./scripts/load_plan.sh`.  A new version is
created only if the content hash differs from the latest stored version.  The
new version is auto-activated on sync.

> **Note:** With `docker-compose.dev.yaml` the `plans/` directory is baked into
> the image — there is no bind-mount by default.  After editing a plan YAML you
> must rebuild the `api` image before re-running the sync script:
>
> ```bash
> docker compose -f docker-compose.dev.yaml build api
> docker compose -f docker-compose.dev.yaml up -d api
> ./scripts/load_plan.sh
> ```
>
> Alternatively, set `OSINT_PLAN_DIR` to a host-mounted directory (add a
> `volumes:` bind-mount in your compose override) so edits are picked up without
> a rebuild.
