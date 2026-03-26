# Ingest Pipeline Stability Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three production bugs: MissingGreenlet on indicator append, domain regex false positives, and NVD connector OOM.

**Architecture:** Each fix is independent — a targeted change to one module plus its tests. Fix 1 touches the ingest/entity workers, Fix 2 touches the indicator extraction service, Fix 3 touches the NVD connector and plan configs. No schema changes, no migrations.

**Tech Stack:** Python 3.12, SQLAlchemy 2.0 (asyncpg), tldextract, pytest + respx, Celery

**Spec:** `docs/superpowers/specs/2026-03-26-ingest-stability-fixes-design.md`

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `src/osint_core/workers/ingest.py` | Modify (lines 180-189) | Initialize indicator collection before append |
| `src/osint_core/workers/k8s_dispatch.py` | Modify (lines 162-169) | Materialize entity collection before mutation |
| `src/osint_core/services/indicators.py` | Modify (lines 1, 75-80) | Add tldextract import and domain validation |
| `src/osint_core/connectors/nvd.py` | Modify (lines 1-38) | Add lookback_hours, max_pages, param filtering |
| `pyproject.toml` | Modify (line 33-34) | Add tldextract dependency |
| `plans/cyber-threat-intel.yaml` | Modify (lines 16-19) | Add lookback_hours to nvd_recent |
| `tests/workers/test_ingest_pipeline.py` | Modify | Add indicator append regression test |
| `tests/workers/test_k8s_dispatch.py` | Create | Entity linking materialization test |
| `tests/test_indicators.py` | Modify | Domain false positive tests |
| `tests/connectors/test_nvd.py` | Modify | lookback_hours and max_pages tests |

---

### Task 1: Fix MissingGreenlet — Ingest Pipeline

**Files:**
- Modify: `src/osint_core/workers/ingest.py:180-189`
- Test: `tests/workers/test_ingest_pipeline.py`

- [ ] **Step 1: Write the regression tests**

Add to `tests/workers/test_ingest_pipeline.py`. Two tests: (a) a focused unit test using a real `Event()` model to prove the lazy-loader bypass works, and (b) a pipeline-level smoke test.

```python
from osint_core.models.event import Event as RealEvent


def test_event_indicators_append_after_hydration():
    """A real Event() with indicators=[] set allows .append() without MissingGreenlet.

    Without the fix, accessing .indicators on a new Event triggers the selectin
    lazy loader, which calls await_only() outside a greenlet context.
    Setting event.indicators = [] bypasses the loader entirely.
    """
    event = RealEvent(
        event_type="rss",
        source_id="test",
        title="Test",
        dedupe_fingerprint="abc123",
    )
    # This is the fix: hydrate collection before appending
    event.indicators = []

    mock_indicator = MagicMock()
    mock_indicator.id = uuid.uuid4()
    event.indicators.append(mock_indicator)

    assert len(event.indicators) == 1
    assert event.indicators[0] is mock_indicator


@pytest.mark.asyncio
async def test_ingest_with_indicators_no_greenlet_error():
    """Pipeline smoke test: items with extractable indicators complete without errors.

    Verifies the full ingest pipeline path through indicator extraction and
    upsert completes successfully when indicators are returned.
    """
    plan = _make_plan()
    items = [_make_raw_item("Threat at evil.example.com", "https://a.com/1")]
    mock_db = _make_mock_db()
    task_self = _mock_task_self()

    event_ids = [uuid.uuid4()]
    event_id_iter = iter(event_ids)
    original_add = mock_db.add

    def side_effect_add(obj):
        if hasattr(obj, "event_type"):
            obj.id = next(event_id_iter)
        return original_add(obj)

    mock_db.add = MagicMock(side_effect=side_effect_add)

    mock_indicator = MagicMock()
    mock_indicator.id = uuid.uuid4()

    mock_chain = MagicMock()
    mock_chain.return_value.apply_async = MagicMock()

    patches = _patch_all(mock_db, plan, items)

    with (
        patch("osint_core.workers.ingest.async_session", patches["async_session"]),
        patch("osint_core.workers.ingest.plan_store", patches["plan_store"]),
        patch("osint_core.workers.ingest.registry", patches["registry"]),
        patch("osint_core.workers.ingest.score_event_task", MagicMock()),
        patch("osint_core.workers.ingest.vectorize_event_task", MagicMock()),
        patch("osint_core.workers.ingest.correlate_event_task", MagicMock()),
        patch("osint_core.workers.ingest.enrich_entities_task", MagicMock()),
        patch("osint_core.workers.ingest.nlp_enrich_task", MagicMock()),
        patch("osint_core.workers.ingest.chain", mock_chain),
        patch("osint_core.workers.ingest.group", MagicMock()),
        patch(
            "osint_core.workers.ingest.extract_indicators",
            return_value=[{"type": "domain", "value": "evil.example.com"}],
        ),
        patch(
            "osint_core.workers.ingest._upsert_indicator",
            new_callable=AsyncMock,
            return_value=mock_indicator,
        ),
    ):
        result = await _ingest_source_async(task_self, "src-1", "plan-1")

    assert result["ingested"] == 1
    assert result["errors"] == 0
    assert result["status"] == "succeeded"
```

- [ ] **Step 2: Run tests to verify baseline**

Run: `cd /root/repos/personal/osint-core && python -m pytest tests/workers/test_ingest_pipeline.py::test_event_indicators_append_after_hydration tests/workers/test_ingest_pipeline.py::test_ingest_with_indicators_no_greenlet_error -v`

Expected: `test_event_indicators_append_after_hydration` should pass even before the fix (it tests the hydration pattern itself). `test_ingest_with_indicators_no_greenlet_error` may fail if the mock Event's `.indicators` attribute isn't writable without the fix. If both pass, that's fine — the unit test proves the fix pattern works, and the pipeline test provides integration coverage.

**Also check the existing test `test_ingest_creates_events` still passes.** That test patches `extract_indicators` to return indicators but does NOT mock `_upsert_indicator`. After the fix, the code will call `_upsert_indicator` when `indicator_dicts` is non-empty. If this test breaks, add a `_upsert_indicator` mock to it (same as the new test does).

- [ ] **Step 3: Implement the fix in ingest.py**

Edit `src/osint_core/workers/ingest.py` lines 180-189. Replace:

```python
                    # Extract and link indicators
                    indicator_dicts = extract_indicators(
                        f"{item.title} {item.summary}"
                    )
                    for ind_dict in indicator_dicts:
                        indicator = await _upsert_indicator(
                            db, ind_dict, source_id
                        )
                        if indicator is not None:
                            event.indicators.append(indicator)
```

With:

```python
                    # Extract and link indicators
                    indicator_dicts = extract_indicators(
                        f"{item.title} {item.summary}"
                    )
                    # Hydrate collection to avoid MissingGreenlet from
                    # selectin lazy loader on a new (unflushed) Event.
                    # Safe here because event is newly created — no
                    # pre-existing indicators to preserve.
                    if indicator_dicts:
                        event.indicators = []
                    for ind_dict in indicator_dicts:
                        indicator = await _upsert_indicator(
                            db, ind_dict, source_id
                        )
                        if indicator is not None:
                            event.indicators.append(indicator)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /root/repos/personal/osint-core && python -m pytest tests/workers/test_ingest_pipeline.py -v`

Expected: ALL tests pass, including the new regression test.

- [ ] **Step 5: Commit**

```bash
git add src/osint_core/workers/ingest.py tests/workers/test_ingest_pipeline.py
git commit -m "fix: initialize indicator collection before append to avoid MissingGreenlet"
```

---

### Task 2: Harden Entity Linking in k8s_dispatch.py

**Files:**
- Modify: `src/osint_core/workers/k8s_dispatch.py:163-169`
- Create: `tests/workers/test_k8s_dispatch.py`

- [ ] **Step 1: Write the test**

Create `tests/workers/test_k8s_dispatch.py`:

```python
"""Tests for entity enrichment in k8s_dispatch."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from osint_core.workers.k8s_dispatch import _enrich_entities_async


def _mock_event(title="Test Event", summary="Summary"):
    """Create a mock Event with a materialized entities list."""
    event = SimpleNamespace(
        id=uuid.uuid4(),
        title=title,
        summary=summary,
        raw_excerpt="https://example.com",
        entities=[],  # pre-materialized
    )
    return event


def _mock_entity(name="Austin", ent_type="LOCATION"):
    entity = SimpleNamespace(id=uuid.uuid4(), name=name, entity_type=ent_type)
    return entity


@pytest.mark.asyncio
async def test_entity_linking_uses_materialized_list():
    """Entities are appended via materialized list, not lazy-loaded collection."""
    event = _mock_event()
    entity_a = _mock_entity("Austin", "LOCATION")
    entity_b = _mock_entity("FBI", "ORG")

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = event
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    mock_session = MagicMock()
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_session.return_value = mock_ctx

    with (
        patch("osint_core.workers.k8s_dispatch.async_session", mock_session),
        patch(
            "osint_core.workers.k8s_dispatch.extract_entities",
            return_value=[
                {"name": "Austin", "type": "LOCATION"},
                {"name": "FBI", "type": "ORG"},
            ],
        ),
        patch(
            "osint_core.workers.k8s_dispatch._upsert_entity",
            new_callable=AsyncMock,
            side_effect=[entity_a, entity_b],
        ),
    ):
        result = await _enrich_entities_async(str(event.id))

    assert result["entities_found"] == 2
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_entity_linking_deduplicates():
    """Same entity returned twice is only linked once."""
    event = _mock_event()
    entity = _mock_entity("Austin", "LOCATION")

    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = event
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    mock_session = MagicMock()
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_session.return_value = mock_ctx

    with (
        patch("osint_core.workers.k8s_dispatch.async_session", mock_session),
        patch(
            "osint_core.workers.k8s_dispatch.extract_entities",
            return_value=[
                {"name": "Austin", "type": "LOCATION"},
                {"name": "Austin", "type": "LOCATION"},
            ],
        ),
        patch(
            "osint_core.workers.k8s_dispatch._upsert_entity",
            new_callable=AsyncMock,
            return_value=entity,
        ),
    ):
        result = await _enrich_entities_async(str(event.id))

    # Only one unique entity should be linked
    assert len(event.entities) == 1
```

- [ ] **Step 2: Run tests to check baseline**

Run: `cd /root/repos/personal/osint-core && python -m pytest tests/workers/test_k8s_dispatch.py -v`

Expected: Tests should pass with the current code (k8s_dispatch loads events from DB, so selectin fires). This establishes the baseline.

- [ ] **Step 3: Apply the defensive hardening**

Edit `src/osint_core/workers/k8s_dispatch.py` lines 162-169. Replace:

```python
        # Upsert each entity and link to event
        linked_count = 0
        for ent_dict in unique_entities:
            entity = await _upsert_entity(db, ent_dict)
            # Link to event if not already linked
            if entity not in event.entities:
                event.entities.append(entity)
                linked_count += 1
```

With:

```python
        # Upsert each entity and link to event.
        # Materialize the selectin-loaded collection into a plain list
        # to avoid re-triggering the lazy loader on each `not in` check
        # and to be safe if this code is ever called on a new Event.
        linked_count = 0
        existing_entities = list(event.entities)
        for ent_dict in unique_entities:
            entity = await _upsert_entity(db, ent_dict)
            if entity not in existing_entities:
                event.entities.append(entity)
                existing_entities.append(entity)
                linked_count += 1
```

- [ ] **Step 4: Run tests to verify everything passes**

Run: `cd /root/repos/personal/osint-core && python -m pytest tests/workers/test_k8s_dispatch.py -v`

Expected: ALL pass.

- [ ] **Step 5: Commit**

```bash
git add src/osint_core/workers/k8s_dispatch.py tests/workers/test_k8s_dispatch.py
git commit -m "fix: materialize entity collection before mutation to harden against lazy loader"
```

---

### Task 3: Fix Domain Regex False Positives

**Files:**
- Modify: `pyproject.toml:37`
- Modify: `src/osint_core/services/indicators.py:1,75-80`
- Test: `tests/test_indicators.py`

- [ ] **Step 1: Add tldextract dependency**

Edit `pyproject.toml` — add `"tldextract>=5.0.0",` to the `dependencies` list (after `"feedparser>=6.0.0",` on line 33):

```
  "feedparser>=6.0.0",
  "tldextract>=5.0.0",
  "weasyprint>=62.0",
```

- [ ] **Step 2: Install the dependency**

Run: `cd /root/repos/personal/osint-core && uv sync 2>&1 | tail -5`

Expected: tldextract installs successfully.

- [ ] **Step 3: Write the failing tests**

Add to `tests/test_indicators.py`:

```python
class TestDomainFalsePositives:
    """Regression tests: sentence fragments must not be extracted as domains."""

    def test_word_dot_word_not_domain(self):
        """'month.The' from cbsaustin RSS must not match as a domain."""
        text = "The robbery occurred last month.The suspect fled on foot."
        indicators = extract_indicators(text)
        domains = [i for i in indicators if i["type"] == "domain"]
        assert domains == []

    def test_multiple_false_positives_rejected(self):
        """Common sentence patterns from news prose must not match."""
        for fragment in [
            "night.Deputies responded to the scene",
            "damages.The fire was caused by",
            "Safety.Troopers arrived at the scene",
            "families.Principal Smith addressed",
        ]:
            indicators = extract_indicators(fragment)
            domains = [i for i in indicators if i["type"] == "domain"]
            assert domains == [], f"False positive domain in: {fragment!r}"

    def test_valid_domain_still_extracted(self):
        """Real domains with valid TLDs must still be extracted."""
        text = "Malware phones home to evil.example.com for C2"
        indicators = extract_indicators(text)
        domains = [i for i in indicators if i["type"] == "domain"]
        assert any(i["value"] == "evil.example.com" for i in domains)

    def test_multi_level_tld_extracted(self):
        """Domains with multi-level TLDs (co.uk, gov.ru) must be extracted."""
        text = "C2 at sub.domain.co.uk and also malware.gov.ru"
        indicators = extract_indicators(text)
        domains = [i for i in indicators if i["type"] == "domain"]
        values = {d["value"] for d in domains}
        assert "sub.domain.co.uk" in values
        assert "malware.gov.ru" in values
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd /root/repos/personal/osint-core && python -m pytest tests/test_indicators.py::TestDomainFalsePositives -v`

Expected: `test_word_dot_word_not_domain` and `test_multiple_false_positives_rejected` FAIL (false positives extracted). `test_valid_domain_still_extracted` passes.

- [ ] **Step 5: Implement the tldextract filter**

Edit `src/osint_core/services/indicators.py`. Add import at the top (after line 2):

```python
import tldextract
```

Replace the domain extraction block (lines 75-80):

```python
    # Domains — skip any that fall inside a URL span
    for m in _DOMAIN_RE.finditer(text):
        start, end = m.start(), m.end()
        in_url = any(us <= start and end <= ue for us, ue in url_spans)
        if not in_url:
            _add("domain", m.group())
```

With:

```python
    # Domains — skip any that fall inside a URL span, then validate TLD
    for m in _DOMAIN_RE.finditer(text):
        start, end = m.start(), m.end()
        in_url = any(us <= start and end <= ue for us, ue in url_spans)
        if in_url:
            continue
        extracted = tldextract.extract(m.group())
        if extracted.suffix:  # has a real TLD per Public Suffix List
            _add("domain", m.group())
```

- [ ] **Step 6: Run all indicator tests**

Run: `cd /root/repos/personal/osint-core && python -m pytest tests/test_indicators.py -v`

Expected: ALL pass, including existing tests and new false-positive tests.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/osint_core/services/indicators.py tests/test_indicators.py
git commit -m "fix: validate domain TLDs with tldextract to reject false positives"
```

---

### Task 4: Fix NVD Connector OOM

**Files:**
- Modify: `src/osint_core/connectors/nvd.py:1-38`
- Test: `tests/connectors/test_nvd.py`

- [ ] **Step 1: Write the failing tests**

Add the following imports to the top of `tests/connectors/test_nvd.py` (after the existing imports):

```python
from unittest.mock import patch
from datetime import timedelta
```

Then add these test functions and fixtures at the bottom of the file:

```python
@pytest.fixture()
def config_with_lookback() -> SourceConfig:
    return SourceConfig(
        id="nvd",
        type="nvd",
        url="https://services.nvd.nist.gov/rest/json/cves/2.0",
        weight=0.8,
        extra={"lookback_hours": 24},
    )


@pytest.fixture()
def connector_with_lookback(config_with_lookback: SourceConfig) -> NvdConnector:
    return NvdConnector(config_with_lookback)


@pytest.mark.asyncio
async def test_lookback_hours_sends_date_params(connector_with_lookback: NvdConnector, respx_mock):
    """When lookback_hours is set, lastModStartDate and lastModEndDate are sent."""
    route = respx_mock.get(connector_with_lookback.config.url).mock(
        return_value=httpx.Response(200, json={
            "resultsPerPage": 0, "startIndex": 0, "totalResults": 0,
            "vulnerabilities": [],
        })
    )
    await connector_with_lookback.fetch()

    request = route.calls[0].request
    assert "lastModStartDate" in str(request.url)
    assert "lastModEndDate" in str(request.url)
    # Must NOT contain connector-only keys
    assert "lookback_hours" not in str(request.url)


@pytest.mark.asyncio
async def test_no_lookback_sends_no_date_filter(connector: NvdConnector, respx_mock):
    """Without lookback_hours, no date params are sent (backwards compat)."""
    route = respx_mock.get(connector.config.url).mock(
        return_value=httpx.Response(200, json=SAMPLE_NVD_RESPONSE)
    )
    await connector.fetch()

    request = route.calls[0].request
    assert "lastModStartDate" not in str(request.url)


@pytest.mark.asyncio
async def test_max_pages_caps_pagination(respx_mock):
    """max_pages=1 stops after one page even when totalResults says more exist."""
    cfg = SourceConfig(
        id="nvd", type="nvd",
        url="https://services.nvd.nist.gov/rest/json/cves/2.0",
        weight=0.8,
        extra={"max_pages": 1},
    )
    connector = NvdConnector(cfg)

    page1 = SAMPLE_NVD_RESPONSE.copy()
    page1["totalResults"] = 10000  # pretend there are many more

    route = respx_mock.get(cfg.url).mock(
        return_value=httpx.Response(200, json=page1)
    )
    items = await connector.fetch()

    # Should have fetched only 1 page (2 items from SAMPLE_NVD_RESPONSE)
    assert len(items) == 2
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_connector_keys_not_sent_to_api(respx_mock):
    """lookback_hours, max_pages, max_items must not be sent as API query params."""
    cfg = SourceConfig(
        id="nvd", type="nvd",
        url="https://services.nvd.nist.gov/rest/json/cves/2.0",
        weight=0.8,
        extra={"lookback_hours": 24, "max_pages": 2, "max_items": 50, "keywordSearch": "apache"},
    )
    connector = NvdConnector(cfg)

    route = respx_mock.get(cfg.url).mock(
        return_value=httpx.Response(200, json={
            "resultsPerPage": 0, "startIndex": 0, "totalResults": 0,
            "vulnerabilities": [],
        })
    )
    await connector.fetch()

    url_str = str(route.calls[0].request.url)
    assert "lookback_hours" not in url_str
    assert "max_pages" not in url_str
    assert "max_items" not in url_str
    # But keywordSearch SHOULD be sent
    assert "keywordSearch=apache" in url_str
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /root/repos/personal/osint-core && python -m pytest tests/connectors/test_nvd.py::test_lookback_hours_sends_date_params tests/connectors/test_nvd.py::test_max_pages_caps_pagination tests/connectors/test_nvd.py::test_connector_keys_not_sent_to_api -v`

Expected: FAIL — current code doesn't support lookback_hours, max_pages, or param filtering.

- [ ] **Step 3: Implement the NVD connector changes**

Rewrite `src/osint_core/connectors/nvd.py` — replace lines 1-38:

```python
"""NVD API 2.0 feed connector."""

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog

from osint_core.connectors.base import BaseConnector, RawItem

logger = structlog.get_logger()

# Keys consumed by the connector, NOT passed to the NVD API.
_CONNECTOR_KEYS = frozenset({"lookback_hours", "max_pages", "max_items"})


class NvdConnector(BaseConnector):
    """Fetches recent CVEs from the NVD API 2.0 with pagination support."""

    RESULTS_PER_PAGE = 2000

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

        # Pass through API-level params, stripping connector-only keys
        for key, value in self.config.extra.items():
            if key not in _CONNECTOR_KEYS:
                params[key] = value

        async with httpx.AsyncClient(timeout=30) as client:
            while True:
                params["startIndex"] = start_index

                resp = await client.get(self.config.url, params=params)
                resp.raise_for_status()
                data = resp.json()

                vulnerabilities = data.get("vulnerabilities", [])
                for entry in vulnerabilities:
                    cve = entry["cve"]
                    items.append(self._parse_cve(cve))

                total = data.get("totalResults", 0)
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

Leave the rest of the file (`_parse_cve`, `_english_description`, `_extract_severity`, `dedupe_key`) unchanged.

- [ ] **Step 4: Run all NVD tests**

Run: `cd /root/repos/personal/osint-core && python -m pytest tests/connectors/test_nvd.py -v`

Expected: ALL pass — existing pagination test still works, new tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/osint_core/connectors/nvd.py tests/connectors/test_nvd.py
git commit -m "fix: add lookback_hours and max_pages to NVD connector to prevent OOM"
```

---

### Task 5: Update Plan Configs

**Files:**
- Modify: `plans/cyber-threat-intel.yaml:16-19`

- [ ] **Step 1: Add lookback_hours to nvd_recent source**

Edit `plans/cyber-threat-intel.yaml` lines 16-19. Replace:

```yaml
  - id: nvd_recent
    type: nvd_json_feed
    url: "https://services.nvd.nist.gov/rest/json/cves/2.0"
    schedule_cron: "15 */2 * * *"
```

With:

```yaml
  - id: nvd_recent
    type: nvd_json_feed
    url: "https://services.nvd.nist.gov/rest/json/cves/2.0"
    schedule_cron: "15 */2 * * *"
    params:
      lookback_hours: 48
      max_pages: 5
```

- [ ] **Step 2: Validate the plan**

Run: `cd /root/repos/personal/osint-core && python -c "import yaml; yaml.safe_load(open('plans/cyber-threat-intel.yaml'))" && echo "YAML valid"`

Expected: `YAML valid`

- [ ] **Step 3: Commit**

```bash
git add plans/cyber-threat-intel.yaml
git commit -m "fix: add lookback_hours to NVD source to prevent full-catalog fetches"
```

---

### Task 6: Run Full Test Suite and Lint

- [ ] **Step 1: Run full test suite**

Run: `cd /root/repos/personal/osint-core && python -m pytest tests/ -v --tb=short 2>&1 | tail -30`

Expected: ALL tests pass.

- [ ] **Step 2: Run linter**

Run: `cd /root/repos/personal/osint-core && python -m ruff check src/osint_core/workers/ingest.py src/osint_core/workers/k8s_dispatch.py src/osint_core/services/indicators.py src/osint_core/connectors/nvd.py`

Expected: No errors.

- [ ] **Step 3: Fix any issues found and commit**

If lint or test failures: fix, re-run, commit the fix.

---

## Infrastructure Note (Out of Repo)

After these code changes are merged, bump worker memory in `cortech-infra`:
- File: `apps/osint/overlays/production/` (worker deployment patch)
- Change: `limits.memory: 3Gi` -> `5Gi`, `requests.memory: 1Gi` -> `2Gi`
- Also update `libertycenter-osint` NVD source via the API: `POST /api/v1/plans` with `lookback_hours: 48` added to `nvd_feeds_recent` params.
