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

The script calls `POST /api/v1/plans:sync-from-disk`, which:

1. Scans `settings.plan_dir` (`/app/plans` inside the container) for `*.yaml` files.
2. Validates each file against the plan JSON Schema (v1 or v2 based on the `version` field).
3. Stores a new `PlanVersion` row if the content hash has changed.
4. **Auto-activates** the newly stored version.

After sync the script verifies the `cyber-threat-intel` plan is active.

## Plan files

There are 8 plan files across two schema versions.  The master plan
(`cortech-osint-master`) defines global defaults and references child plans;
child plans carry the actual source definitions.

| File | `plan_id` | Version | Type | Sources | Description |
|------|-----------|---------|------|---------|-------------|
| `plans/cortech-osint-master.yaml` | `cortech-osint-master` | v2 | master | 0 | Master plan -- global defaults, watch regions, child plan references |
| `plans/cyber-threat-intel.yaml` | `cyber-threat-intel` | v2 | child | 9 | Cyber threat intelligence -- CISA KEV, NVD, OSV/PyPI, URLhaus, ThreatFox, OTX, MalwareBazaar, Feodo Tracker, RSS/Hacker News |
| `plans/military-intel.yaml` | `military-intel` | v2 | child | 10 | Military and conflict intelligence -- GDELT, ISW, BBC (world/mideast/europe), Bellingcat, UK MoD, CrisisWatch, Shodan |
| `plans/humanitarian-intel.yaml` | `humanitarian-intel` | v2 | child | 4 | Humanitarian and human rights -- ReliefWeb, HRW, Amnesty, ACLED |
| `plans/austin-terror-threat.yaml` | `austin-terror-threat` | v2 | child | 10 | Austin/Travis County terrorism and mass violence monitoring -- GDELT, local RSS (KXAN, KVUE, CBS, Fox 7), FBI, NWS, ACLED, Reddit, xAI X search |
| `plans/austin-terror-watch.yaml` | `austin-terror-watch` | v2 | child | 6 | Austin terror watch (lighter variant) -- GDELT, CBS Austin, KXAN, FBI, NWS, ACLED |
| `plans/cal-prospecting.yaml` | `cal-prospecting` | v2 | child | 14 | Constitutional rights prospecting for The Center For American Liberty -- xAI X search (CA/TX/MN/DC), RSS (FIRE, Higher Ed Dive, Volokh, Courthouse News), university policy monitors (UC, CSU, UT, TAMU, UMN, UDC) |
| `plans/example.yaml` | `libertycenter-osint` | v1 | -- | 6 | Example/reference plan (v1 schema) |

### Connector types used across plans

The plan schema defines 22 connector types.  The following 17 are actively used
in at least one plan file:

| Connector type | Plans using it |
|----------------|---------------|
| `rss` | cyber-threat-intel, military-intel, humanitarian-intel, austin-terror-threat, austin-terror-watch, cal-prospecting, example |
| `gdelt_api` | military-intel, austin-terror-threat, austin-terror-watch |
| `cisa_kev` | cyber-threat-intel, example |
| `nvd_json_feed` | cyber-threat-intel, example |
| `osv_api` | cyber-threat-intel, example |
| `urlhaus_api` | cyber-threat-intel, example |
| `threatfox_api` | cyber-threat-intel, example |
| `otx_api` | cyber-threat-intel |
| `abusech_malwarebazaar` | cyber-threat-intel |
| `abusech_feodotracker` | cyber-threat-intel |
| `reliefweb_api` | humanitarian-intel |
| `acled_api` | humanitarian-intel, austin-terror-threat, austin-terror-watch |
| `shodan_api` | military-intel |
| `nws_alerts` | austin-terror-threat, austin-terror-watch |
| `reddit` | austin-terror-threat |
| `xai_x_search` | austin-terror-threat, cal-prospecting |
| `university_policy` | cal-prospecting |

Five schema-defined types are not yet used in any plan: `sitemap`,
`http_html`, `http_pdf`, `http_json`, `github_releases`.

### Plan templates

Pre-built plan templates are available in `plans/templates/` for common
collection patterns: `brand-reputation.yaml`, `cyber-threat-intel.yaml`,
`geopolitical-monitoring.yaml`, and `physical-security.yaml`.

## Plan schema

Plans are validated against a JSON Schema (`src/osint_core/schemas/plan-v1.schema.json`
or `src/osint_core/schemas/plan-v2.schema.json`) selected by the `version` field.  The v2 schema adds
support for `plan_type` (master/child), `parent_plan_id`, `keywords`,
`source_profiles`, `enrichment`, `target_geo`, and `custom` sections.

The `PlanEngine` (`src/osint_core/services/plan_engine.py`) performs:

- YAML parsing and JSON Schema validation
- Secret scanning (rejects files with embedded API keys or tokens)
- Content hashing (SHA-256) for change detection
- Celery Beat schedule generation from source `schedule_cron` fields

## Plan API reference

The plan API is mounted at `/api/v1/plans` (see
`src/osint_core/api/routes/plan.py`).

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/api/v1/plans` | List all active plan versions (paginated) |
| `POST` | `/api/v1/plans` | Create and optionally activate a new plan version from YAML |
| `POST` | `/api/v1/plans:validate` | Validate a plan YAML payload without persisting |
| `POST` | `/api/v1/plans:sync-from-disk` | Reload plan files from `settings.plan_dir`, validate, store changed versions, and auto-activate |
| `GET` | `/api/v1/plans/{plan_id}/active-version` | Get the currently active version of a plan |
| `PATCH` | `/api/v1/plans/{plan_id}/active-version` | Activate a specific version by UUID, or roll back to the previous version |
| `GET` | `/api/v1/plans/{plan_id}/versions` | List all stored versions for a plan (paginated, newest first) |
| `GET` | `/api/v1/plans/{plan_id}/versions/{version_id}` | Get a specific stored plan version by UUID |

## Triggering an ingest manually

Once a plan is active you can trigger a single source:

```bash
curl -X POST "http://localhost:8000/api/v1/ingest/source/cisa_kev/run?plan_id=cyber-threat-intel"
```

## Updating a plan

Edit the YAML file and re-run `./scripts/load_plan.sh`.  A new version is
created only if the content hash differs from the latest stored version.  The
new version is auto-activated on sync.
