# End-to-End Ingest Verification

This document describes how to verify that the OSINT-Core ingest pipeline is working correctly from trigger to database persistence.

## Prerequisites

- Docker Compose stack running (`docker compose -f docker-compose.dev.yaml up -d`)
- An active plan synced to the database (`POST /api/v1/plan/sync`)
- `curl` and `jq` installed on the host machine

## Pipeline Overview

The ingest pipeline follows this flow:

```
Manual trigger (API) or Beat scheduler
  → Celery task: osint.ingest_source
    → Connector fetches data from external source
    → Events are deduplicated and written to osint.events
    → Indicators are extracted (CVEs, IPs, URLs, hashes, domains)
    → Indicators are upserted into osint.indicators
    → Downstream tasks chained (score, vectorize, correlate)
    → Job record written to osint.jobs with final status
```

## Automated Verification

Run the verification script from the project root:

```bash
./scripts/verify_ingest.sh [SOURCE_ID] [PLAN_ID]
```

Defaults: `SOURCE_ID=cisa_kev`, `PLAN_ID=libertycenter-osint`.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `API_BASE_URL` | `http://localhost:8000` | Base URL of the API |
| `API_TOKEN` | _(empty)_ | Bearer token — required when `auth_disabled=false` (e.g. staging/prod) |
| `CURL_TIMEOUT` | `30` | Max seconds per individual curl request |
| `POLL_INTERVAL` | `5` | Seconds between job status polls |
| `POLL_TIMEOUT` | `120` | Max seconds to wait for job completion |

### What the Script Checks

| Step | Check | Pass Criteria |
|------|-------|---------------|
| 0 | API health | `/healthz` returns 200 |
| 1 | Dispatch ingest | `POST /api/v1/ingest/source/{id}/run` returns `status: dispatched` |
| 2 | Job completion | Job status = `succeeded` or `partial_success` |
| 3 | Events in DB | `GET /api/v1/events?source_id={id}` returns `total > 0` |
| 4 | Indicators extracted | `GET /api/v1/indicators` returns `total > 0` |
| 5 | Job output | Job `output.ingested > 0` |

## Manual Verification Steps

### 1. Ensure the Stack Is Running

```bash
docker compose -f docker-compose.dev.yaml up -d
```

Verify all services are healthy:

```bash
curl -s http://localhost:8000/healthz | jq .
# Expected: {"status": "ok"}
```

### 2. Sync and Activate a Plan

```bash
# Sync plan files from disk into the database
curl -s -X POST http://localhost:8000/api/v1/plan/sync | jq .

# Verify an active plan exists
curl -s http://localhost:8000/api/v1/plan/active?plan_id=libertycenter-osint | jq .
```

### 3. Trigger Manual Ingest

```bash
curl -s -X POST \
  "http://localhost:8000/api/v1/ingest/source/cisa_kev/run?plan_id=libertycenter-osint" \
  | jq .
```

Expected response:

```json
{
  "task_id": "abc123-...",
  "source_id": "cisa_kev",
  "plan_id": "libertycenter-osint",
  "status": "dispatched"
}
```

### 4. Check Job Status

Poll the jobs endpoint until the job completes:

```bash
curl -s "http://localhost:8000/api/v1/jobs?limit=5" | jq '.items[] | select(.input_params.source_id == "cisa_kev") | {id, status, output, error}'
```

Expected: `status` should be `succeeded`. The `output` field contains counts:

```json
{
  "id": "...",
  "status": "succeeded",
  "output": {
    "ingested": 25,
    "skipped": 3,
    "errors": 0
  },
  "error": null
}
```

### 5. Verify Events

```bash
curl -s "http://localhost:8000/api/v1/events?source_id=cisa_kev&limit=5" | jq '{total, sample: .items[0].title}'
```

Expected: `total > 0` with meaningful event titles.

### 6. Verify Indicators

```bash
curl -s "http://localhost:8000/api/v1/indicators?limit=10" | jq '{total, types: [.items[].indicator_type] | unique}'
```

Expected: `total > 0` with indicator types such as `cve`, `ip`, `url`, `domain`, or `hash`.

## Troubleshooting

### API returns 404 on ingest endpoint

Ensure the API service is running and the router is registered in `src/osint_core/main.py`.

### Job status is `failed`

Check the job's `error` field:

```bash
curl -s "http://localhost:8000/api/v1/jobs/{job_id}" | jq '.error'
```

Common causes:
- No active plan version in the database — run `POST /api/v1/plan/sync` then `POST /api/v1/plan/activate/{version_id}`
- External source is unreachable — check network and source URL
- Connector error — check worker logs: `docker compose -f docker-compose.dev.yaml logs worker`

### No indicators extracted

Some sources may not produce text containing IOCs. Try a source known to have CVEs or URLs (e.g., `cisa_kev`, `urlhaus_recent`, `threatfox_iocs`).

### Job stuck in `running`

Check that the Celery worker is running:

```bash
docker compose -f docker-compose.dev.yaml logs worker --tail=50
```

Check Redis connectivity:

```bash
docker compose -f docker-compose.dev.yaml exec redis redis-cli ping
# Expected: PONG
```

## Verification for Different Sources

The script works with any configured source. Examples:

```bash
# CISA Known Exploited Vulnerabilities
./scripts/verify_ingest.sh cisa_kev libertycenter-osint

# URLhaus malware URLs
./scripts/verify_ingest.sh urlhaus_recent libertycenter-osint

# ThreatFox IOC feed
./scripts/verify_ingest.sh threatfox_iocs libertycenter-osint

# NVD CVE feed
./scripts/verify_ingest.sh nvd_feeds_recent libertycenter-osint
```
