# OSINT-Core Operations Runbook

## Quick Reference

| Task | Command |
|------|---------|
| Start dev stack | `docker compose -f docker-compose.dev.yaml up -d` |
| Sync plans | `curl -s -X POST http://localhost:8000/api/v1/plan/sync \| jq .` |
| Trigger ingest | `curl -s -X POST "http://localhost:8000/api/v1/ingest/source/{source_id}/run?plan_id={plan_id}" \| jq .` |
| Check jobs | `curl -s http://localhost:8000/api/v1/jobs?limit=10 \| jq .` |
| View worker logs | `docker compose -f docker-compose.dev.yaml logs worker --tail=100` |
| Run E2E verification | `./scripts/verify_ingest.sh [source_id] [plan_id]` |

## End-to-End Ingest Verification

After deploying or making changes to the ingest pipeline, run the verification script to confirm everything works:

```bash
./scripts/verify_ingest.sh
```

This checks: task dispatch, job completion, event persistence, indicator extraction, and job output counts. See [docs/verification.md](verification.md) for full details, manual steps, and troubleshooting.

## Common Operations

### Starting Fresh

```bash
docker compose -f docker-compose.dev.yaml down -v
docker compose -f docker-compose.dev.yaml up -d
# Wait for postgres to initialize, then run migrations
docker compose -f docker-compose.dev.yaml exec api alembic upgrade head
# Sync plans
curl -s -X POST http://localhost:8000/api/v1/plan/sync | jq .
```

### Checking Pipeline Health

1. **API**: `curl -s http://localhost:8000/healthz`
2. **Redis**: `docker compose -f docker-compose.dev.yaml exec redis redis-cli ping`
3. **Worker**: `docker compose -f docker-compose.dev.yaml logs worker --tail=20`
4. **Beat**: `docker compose -f docker-compose.dev.yaml logs beat --tail=20`

### Retrying a Failed Job

```bash
curl -s -X POST http://localhost:8000/api/v1/jobs/{job_id}/retry | jq .
```

## CI/CD Database Migrations

### How migrations run

Alembic migrations run automatically on every push to `main` as part of the CI/CD pipeline.
The `migrate` job runs `alembic upgrade head` on the self-hosted runner before the deploy
job proceeds. If the migration fails, the deploy is blocked.

### Manual migration run

Trigger via GitHub Actions:

1. Go to **Actions** > **CI** workflow
2. Click **Run workflow**
3. Set **Run only the migrate job** to `true`
4. Click **Run workflow**

This runs only the `migrate` job (lint/test/build/scan/deploy are all skipped).

### Rolling back a migration

**On the self-hosted runner:**

```bash
# SSH into the runner, navigate to a checkout of osint-core
export OSINT_DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/osint"
pip install -e "."
python -m alembic downgrade -1
```

**Important:** This only works if the migration file has a working `downgrade()` function.
Always verify downgrade functions exist before relying on this.

### When to roll back

- Migration was applied but the subsequent deploy failed, and the new code depends on the
  old schema.
- Migration introduced a breaking schema change that needs reverting before a code fix is
  ready.

### Future enhancements

- **Pre-migration database backup:** Not yet implemented. Will be added once the backup
  strategy is decided.
- **`workflow_dispatch` downgrade:** A future `migration_command` input will allow running
  `alembic downgrade -1` via the Actions UI without SSH access.
