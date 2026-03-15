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
