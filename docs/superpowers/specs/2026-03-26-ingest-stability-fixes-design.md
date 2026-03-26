# Ingest Pipeline Stability Fixes — Design Spec

**Date:** 2026-03-26
**Status:** Approved
**Scope:** Fix three production bugs: MissingGreenlet on indicator append, domain regex false positives, NVD connector OOM

---

## Problem Statement

The Austin terrorism signal scan revealed three bugs affecting ingestion reliability:

1. **cbsaustin_rss fails 100% of new items** — `MissingGreenlet` exception when appending indicators to a newly created Event. SQLAlchemy's `selectin` lazy loader fires in an async context without a greenlet, crashing on `event.indicators.append(indicator)` at `ingest.py:189`.

2. **Domain regex extracts false positives** — The indicator extractor's domain regex matches sentence fragments like `month.The`, `night.Deputies`, `Safety.Troopers` because it accepts any 2–63 letter sequence as a TLD. Every cbsaustin RSS item triggers false domain extraction, which then hits bug #1.

3. **Workers OOMKilled every ~11 minutes** — The NVD connector paginates the entire NVD database (250k+ CVEs) into memory with no date filter or page cap. Combined with the sentence-transformers model (~500MB resident), workers exceed the 3Gi limit and get killed. Tasks in-flight are lost, causing jobs like `acled_us` and `reddit_austin` to stay stuck in `queued`.

---

## Fix 1: MissingGreenlet on Relationship Append

### Root Cause

`Event.indicators` uses `lazy="selectin"`. On a newly created Event (not loaded from DB), accessing `.indicators` triggers the selectin loader, which calls `await_only()` outside a greenlet context.

### Changes

**`src/osint_core/workers/ingest.py`** — Initialize the collection before appending:

```python
# After flush succeeds, before indicator loop
indicator_dicts = extract_indicators(f"{item.title} {item.summary}")
if indicator_dicts:
    event.indicators = []  # bypass lazy loader on new object
for ind_dict in indicator_dicts:
    indicator = await _upsert_indicator(db, ind_dict, source_id)
    if indicator is not None:
        event.indicators.append(indicator)
```

Only hydrates the collection when indicators will actually be appended. **Note:** This is safe because the Event is newly created in this transaction — it has no pre-existing indicator relationships. Do not use this pattern on Events loaded from the DB (which may have existing indicators); in that case, materialize with `list()` instead.

**`src/osint_core/workers/k8s_dispatch.py`** — Defensive hardening. The Event is loaded from DB so selectin fires during the query, but we materialize before mutation to prevent re-triggering the loader on each `not in` check:

```python
linked_count = 0
existing_entities = list(event.entities)  # materialize selectin result
for ent_dict in unique_entities:
    entity = await _upsert_entity(db, ent_dict)
    if entity not in existing_entities:
        event.entities.append(entity)
        existing_entities.append(entity)
        linked_count += 1
```

This also fixes a perf issue — the original `entity not in event.entities` could re-trigger the loader on each iteration.

### Tests

- Regression test: ingest pipeline processes an item that extracts indicators without MissingGreenlet. Must use a real `Event()` model instance (not fully mocked) to exercise the lazy loader bypass.
- Unit test: new Event with `indicators = []` set explicitly allows `.append()` without triggering selectin loader
- k8s_dispatch: test entity linking on a loaded Event with materialized collection. **Note:** `tests/workers/test_k8s_dispatch.py` does not exist yet — create it.

---

## Fix 2: Domain Regex False Positives

### Root Cause

The domain regex `(?<![/@\w])(?:[a-zA-Z0-9]...)+[a-zA-Z]{2,63}\b` accepts any 2–63 letter sequence as a TLD. English prose with missing spaces after periods (e.g., `"last month.The suspect"`) matches as domain `month.The`.

### Changes

**`pyproject.toml`** — Add `tldextract` dependency.

**`src/osint_core/services/indicators.py`** — Post-filter domain candidates:

```python
import tldextract

for m in _DOMAIN_RE.finditer(text):
    start, end = m.start(), m.end()
    in_url = any(us <= start and end <= ue for us, ue in url_spans)
    if in_url:
        continue
    extracted = tldextract.extract(m.group())
    if extracted.suffix:  # has a real TLD per Public Suffix List
        _add("domain", m.group())
```

`tldextract` uses Mozilla's Public Suffix List. `tldextract.extract("month.The").suffix` returns `""` (rejected). `tldextract.extract("evil.example.com").suffix` returns `"com"` (accepted). The library ships with a bundled PSL snapshot — no network calls are made at runtime unless explicitly requested.

### Tests

- Positive: `evil.example.com`, `sub.domain.co.uk`, `malware.gov.ru` — extracted as domains
- Negative: `month.The`, `night.Deputies`, `damages.The`, `Safety.Troopers` — zero domain indicators
- Prose: `"The fire occurred last month.The suspect fled."` — no domains extracted
- Existing tests remain unchanged

---

## Fix 3: NVD Connector OOM

### Root Cause

`NvdConnector.fetch()` paginates the entire NVD feed into memory with no date filter or page cap. The NVD sources in `cyber-threat-intel` and `libertycenter-osint` plans pass no params, so every run fetches 250k+ CVEs (~2000/page × 125+ pages). Each CVE's raw JSON is stored in the `RawItem.raw_data` dict, consuming gigabytes.

### Changes

**`src/osint_core/connectors/nvd.py`** — Add `lookback_hours` and `max_pages`. Also add `timedelta` to the existing `from datetime import UTC, datetime` import, and add `structlog` for the warning log.

```python
# Keys consumed by the connector, NOT passed to the NVD API
_CONNECTOR_KEYS = frozenset({"lookback_hours", "max_pages", "max_items"})

async def fetch(self) -> list[RawItem]:
    items: list[RawItem] = []
    start_index = 0
    max_pages = int(self.config.extra.get("max_pages", 5))
    pages_fetched = 0

    params: dict[str, Any] = {"resultsPerPage": self.RESULTS_PER_PAGE}

    # Time-window filter — only fetch recently modified CVEs
    lookback_hours = self.config.extra.get("lookback_hours")
    if lookback_hours:
        start_date = datetime.now(UTC) - timedelta(hours=int(lookback_hours))
        params["lastModStartDate"] = start_date.isoformat()
        params["lastModEndDate"] = datetime.now(UTC).isoformat()

    # Pass through any remaining API-level params (e.g., keywordSearch),
    # but strip connector-only keys that the NVD API doesn't accept.
    for key, value in self.config.extra.items():
        if key not in _CONNECTOR_KEYS:
            params[key] = value

    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            params["startIndex"] = start_index
            # ... existing fetch + parse logic ...

            pages_fetched += 1
            if pages_fetched >= max_pages:
                logger.warning(
                    "nvd_max_pages_reached",
                    max_pages=max_pages,
                    total_results=total,
                    fetched=len(items),
                )
                break

            start_index += len(vulnerabilities)
            if start_index >= total:
                break

    return items
```

Key design decisions:
- **Param filtering**: `_CONNECTOR_KEYS` is a frozenset of keys consumed by the connector. These are stripped from the params dict before sending to the NVD API. All other `config.extra` keys are passed through as API params (e.g., `keywordSearch`). This replaces the existing `params.update(self.config.extra)` call.
- **Date format**: Uses `datetime.isoformat()` which produces ISO 8601 with timezone (e.g., `2026-03-24T03:11:53+00:00`), as required by the NVD API 2.0.
- **Timeout**: Adds explicit `timeout=30` (the current code uses httpx defaults of ~5s per phase). This is an intentional change since the NVD API can be slow under load.
- `lookback_hours`: optional. If unset, no date filter (backwards compatible). Uses `lastModStartDate`/`lastModEndDate`.
- `max_pages`: defaults to 5 (10,000 CVEs max). Safety net. **Note:** This intentionally caps full-DB fetches for any NVD source without `lookback_hours`. This is the desired behavior to prevent OOM.
- Connector type is registered as `nvd_json_feed` in the registry — plan configs already use this type string.

**Plan configs** — Update both NVD sources:

```yaml
# cyber-threat-intel: nvd_recent
params:
  lookback_hours: 48
  max_pages: 5

# libertycenter-osint: nvd_feeds_recent
params:
  lookback_hours: 48
  max_pages: 5
```

**Infrastructure (cortech-infra repo)** — Bump worker memory:
- `limits.memory`: 3Gi → 5Gi
- `requests.memory`: 1Gi → 2Gi

This is a manual change in `cortech-infra/apps/osint/overlays/production/`.

### Tests

- Unit test: `lookback_hours=24` sends correct ISO 8601 `lastModStartDate` param to NVD API
- Unit test: `max_pages=2` stops after 2 pages even if `totalResults` says more exist. Verify the HTTP mock is called exactly 2 times.
- Unit test: no `lookback_hours` sends no date filter (backwards compat)
- Unit test: `lookback_hours` and `max_pages` are NOT sent as NVD API query params (filtered by `_CONNECTOR_KEYS`)
- Unit test: other `config.extra` keys (e.g., `keywordSearch`) ARE passed through to the API

---

## Files Changed

| File | Change |
|------|--------|
| `src/osint_core/workers/ingest.py` | Initialize `event.indicators = []` before append loop |
| `src/osint_core/workers/k8s_dispatch.py` | Materialize `event.entities` before mutation loop |
| `src/osint_core/services/indicators.py` | Add `tldextract` validation to domain extraction |
| `src/osint_core/connectors/nvd.py` | Add `lookback_hours` and `max_pages` support |
| `pyproject.toml` | Add `tldextract` dependency |
| `plans/cyber-threat-intel.yaml` | Add `lookback_hours: 48` to nvd_recent |
| `plans/libertycenter-osint.yaml` | Add `lookback_hours: 48` to nvd_feeds_recent (DB-only plan — update via API or sync-from-disk if plan file is added) |
| `tests/workers/test_ingest_pipeline.py` | MissingGreenlet regression test |
| `tests/workers/test_k8s_dispatch.py` | Entity linking hardening test |
| `tests/test_indicators.py` | Domain false positive tests |
| `tests/connectors/test_nvd.py` | lookback_hours and max_pages tests |

## Out of Scope

- Changing `lazy="selectin"` to a different strategy on the Event model (read paths work fine)
- Refactoring the domain regex itself (tldextract validation is sufficient)
- Celery `acks_late` changes (already configured correctly)
- ACLED credential verification (separate operational task)
