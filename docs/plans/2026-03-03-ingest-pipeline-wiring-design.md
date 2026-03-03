# Ingest Pipeline Wiring Design

**Date:** 2026-03-03
**Status:** Approved
**Branch:** feat/cicd-pipeline-redesign

## Problem

The `osint.ingest_source` Celery task is a stub that returns `{"ingested": 0}` immediately. All supporting infrastructure (connectors, models, services) is built and tested, but the task doesn't actually fetch, deduplicate, or persist events.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Async strategy | `asyncio.run()` wrapper | Simple, proven, connectors are async |
| Architecture | Minimal wiring (Approach A) | Single function in `workers/ingest.py`, no new abstractions |
| plan_id | Required argument | Eliminates ambiguity; source_id can collide across plans |
| Downstream chaining | Wire now | Stubs no-op until implemented; wiring is ready |
| Error handling | Celery retry + per-item catch | Retry transient failures; count item errors |
| Job status | Add `partial_success` | Requires Alembic migration on CHECK constraint |

## Task Signature

```python
@celery_app.task(bind=True, name="osint.ingest_source", max_retries=3)
def ingest_source(self, source_id: str, plan_id: str) -> dict[str, Any]:
    try:
        return asyncio.run(_ingest_source_async(self, source_id, plan_id))
    except (ValueError, KeyError) as exc:
        logger.error("Ingest config error: %s", exc)
        # Config errors — don't retry, record failed Job
        asyncio.run(_record_job(self, source_id, plan_id, "failed", error=str(exc)))
        return {"source_id": source_id, "status": "failed", "error": str(exc), ...}
    except Exception as exc:
        countdown = min(2 ** self.request.retries * 30, 900)  # cap at 15 min
        raise self.retry(exc=exc, countdown=countdown)
```

## Core Logic (`_ingest_source_async`)

### Step 1: Resolve Plan & Source Config

```python
async with async_session() as db:
    plan = await plan_store.get_active(db, plan_id)
    if not plan:
        raise ValueError(f"No active plan for plan_id={plan_id}")

    source_cfg_dict = next(
        (s for s in plan.content["sources"] if s["id"] == source_id), None
    )
    if not source_cfg_dict:
        raise ValueError(f"Source {source_id} not in plan {plan_id}")

    source_cfg = SourceConfig(
        id=source_cfg_dict["id"],
        type=source_cfg_dict["type"],
        url=source_cfg_dict.get("url", ""),
        weight=source_cfg_dict.get("weight", 1.0),
        extra=source_cfg_dict.get("params", {}),
    )
```

### Step 2: Fetch Items

```python
    connector = registry.get(source_cfg.type, source_cfg)
    items = await connector.fetch()
```

### Step 3: Dedupe & Persist (Per-Item)

For each item:
1. Compute `_dedupe_fingerprint(source_id, item.raw_data)`
2. Pre-check: `SELECT id FROM events WHERE dedupe_fingerprint = ?` (fast path skip)
3. Create Event with all fields populated from RawItem + SourceConfig
4. `db.flush()` — catch `IntegrityError` on dedupe_fingerprint (concurrent race), count as skipped
5. Extract indicators via `extract_indicators(f"{item.title} {item.summary}")`
6. For each indicator: try insert, catch `IntegrityError` (concurrent upsert), re-select existing
7. Merge `source_id` into `indicator.sources` if not already present
8. Append indicator to `event.indicators`
9. Collect `event.id` into `new_event_ids` list

### Step 4: Error Rate Check

```python
ERROR_RATE_THRESHOLD = 0.5
if items and errors / len(items) > ERROR_RATE_THRESHOLD:
    raise RuntimeError(f"High error rate: {errors}/{len(items)} items failed")
```

If >50% of items fail, raise to trigger Celery retry (may be systemic issue like upstream API change).

### Step 5: Commit & Chain Downstream

```python
await db.commit()

for event_id in new_event_ids:
    score_event_task.delay(event_id)
    vectorize_event_task.delay(event_id)
    correlate_event_task.delay(event_id)
```

### Step 6: Record Job

```python
if errors > 0 and ingested > 0:
    job_status = "partial_success"
elif errors > 0:
    job_status = "failed"
else:
    job_status = "succeeded"

job = Job(
    job_type="ingest",
    status=job_status,
    celery_task_id=self.request.id,
    plan_version_id=plan.id,
    input_params={"source_id": source_id, "plan_id": plan_id},
    output={"ingested": ingested, "skipped": skipped, "errors": errors},
)
```

## Concurrency Safety

- **Dedupe race:** Pre-check SELECT + IntegrityError catch on INSERT. If two workers process the same item simultaneously, one succeeds and the other counts it as skipped.
- **Indicator upsert race:** Try INSERT, catch IntegrityError, re-SELECT existing, then link. Merge `source_id` into `sources` array only if missing.
- **Session rollback:** On IntegrityError, rollback the failed flush before continuing to next item.

## Files Changed

| File | Change |
|------|--------|
| `src/osint_core/workers/ingest.py` | Replace stub with full implementation (~90 lines) |
| `src/osint_core/services/plan_engine.py` | Pass `plan_id` in Beat schedule task kwargs |
| `src/osint_core/api/routes/ingest.py` | Accept & pass required `plan_id` to task dispatch |
| `alembic/versions/0004_*.py` | Migration: add `partial_success` to Job status CHECK |
| `tests/unit/test_ingest_task.py` | Unit tests for ingest task logic |

**Unchanged:** Connectors, Event/Indicator/Job models, PlanStore, indicator service, db.py.

## Testing Strategy

- Mock connectors to return known RawItems
- Mock or use test DB for persistence
- Verify: events created with correct fields, indicators linked, dedupe skips duplicates
- Verify: IntegrityError handling for concurrent dedupe and indicator races
- Verify: error rate threshold triggers RuntimeError (Celery retry)
- Verify: retry backoff capped at 900s
- Verify: Job recorded with correct status (succeeded/partial_success/failed)
- Verify: downstream tasks chained with correct event IDs
