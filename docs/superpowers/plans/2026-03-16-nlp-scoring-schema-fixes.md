# NLP Enrichment, Scoring, and Schema Fixes — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix plan schema validation, migrate NLP enrichment from Ollama to vLLM (OpenAI-compatible), and fix Celery routing so that plan sync, NLP enrichment, and scoring all work end-to-end.

**Architecture:** Three independent workstreams: (1) schema fixes unblock plan sync, (2) LLM migration rewrites the inference call path from Ollama native to OpenAI chat completions via httpx, (3) Celery config adds explicit nlp_enrich registration. All changes are in the same PR branch `fix/idempotent-migrations`.

**Tech Stack:** Python 3.10+, Alembic, SQLAlchemy, Celery, httpx, jsonschema, pytest, respx

**Spec:** `docs/superpowers/specs/2026-03-16-nlp-scoring-schema-fixes-design.md`

---

## Chunk 1: Plan Schema and YAML Fixes

### Task 1: Add enrichment and target_geo to v2 schema

**Files:**
- Modify: `src/osint_core/schemas/plan-v2.schema.json:88-101` (top-level properties)
- Test: `tests/test_plan_engine.py`

- [ ] **Step 1: Write a failing test — v2 child plan with enrichment and target_geo**

Add to `tests/test_plan_engine.py`:

```python
def test_validate_v2_child_with_enrichment_and_target_geo():
    """v2 child plan with enrichment and target_geo must pass validation."""
    engine = PlanEngine()
    yaml_str = """
version: 2
plan_id: austin-terror-watch
plan_type: child
sources:
  - id: gdelt_austin
    type: gdelt_api
    url: "https://api.gdeltproject.org/api/v2/doc/doc"
scoring:
  recency_half_life_hours: 168
  source_reputation:
    gdelt_austin: 0.53
  ioc_match_boost: 2.0
notifications:
  routes:
    - name: alerts
      channels:
        - type: gotify
enrichment:
  nlp_enabled: true
  mission: "Monitor terror threats in Austin"
target_geo:
  country_codes: ["USA"]
  lat: 30.2672
  lon: -97.7431
  radius_km: 100
keywords:
  - terrorism
  - attack
"""
    result = engine.validate_yaml(yaml_str)
    assert result.is_valid, f"Errors: {result.errors}"
    assert result.parsed["enrichment"]["nlp_enabled"] is True
    assert result.parsed["target_geo"]["lat"] == 30.2672
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_plan_engine.py::test_validate_v2_child_with_enrichment_and_target_geo -v`
Expected: FAIL — schema rejects `enrichment` and `target_geo` as additional properties.

- [ ] **Step 3: Add $ref entries to plan-v2.schema.json**

In `src/osint_core/schemas/plan-v2.schema.json`, add two properties to the top-level `properties` object (after `source_profiles` at ~line 100):

```json
    "enrichment": {
      "$ref": "#/$defs/enrichment"
    },
    "target_geo": {
      "$ref": "#/$defs/target_geo"
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_plan_engine.py -v`
Expected: ALL PASS including the new test.

- [ ] **Step 5: Commit**

```bash
git add src/osint_core/schemas/plan-v2.schema.json tests/test_plan_engine.py
git commit -m "fix(schema): wire enrichment and target_geo into v2 plan schema"
```

### Task 2: Bump cyber-threat-intel.yaml to v2

**Files:**
- Modify: `plans/cyber-threat-intel.yaml:1` (version) and add plan_type

- [ ] **Step 1: Write a failing test — validate cyber-threat-intel.yaml from disk**

Add to `tests/test_plan_engine.py`:

```python
from pathlib import Path

def test_validate_cyber_threat_intel_yaml():
    """cyber-threat-intel.yaml must pass validation."""
    engine = PlanEngine()
    plan_path = Path(__file__).resolve().parents[1] / "plans" / "cyber-threat-intel.yaml"
    yaml_str = plan_path.read_text()
    result = engine.validate_yaml(yaml_str)
    assert result.is_valid, f"Errors: {result.errors}"
    assert result.parsed["version"] == 2
    assert result.parsed["plan_type"] == "child"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_plan_engine.py::test_validate_cyber_threat_intel_yaml -v`
Expected: FAIL — version is 1, plan_type missing.

- [ ] **Step 3: Edit cyber-threat-intel.yaml**

In `plans/cyber-threat-intel.yaml`, change line 1 and add plan_type after plan_id:

```yaml
version: 2
plan_id: cyber-threat-intel
plan_type: child
description: >-
```

(Replace `version: 1` with `version: 2`, add `plan_type: child` line after `plan_id`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_plan_engine.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add plans/cyber-threat-intel.yaml tests/test_plan_engine.py
git commit -m "fix(plans): bump cyber-threat-intel to v2 with plan_type child"
```

### Task 3: Increase austin-terror-watch recency half-life

**Files:**
- Modify: `plans/austin-terror-watch.yaml:109`

- [ ] **Step 1: Write a failing test — validate recency value from disk**

Add to `tests/test_plan_engine.py`:

```python
def test_validate_austin_terror_watch_yaml():
    """austin-terror-watch.yaml must pass validation with updated recency."""
    engine = PlanEngine()
    plan_path = Path(__file__).resolve().parents[1] / "plans" / "austin-terror-watch.yaml"
    yaml_str = plan_path.read_text()
    result = engine.validate_yaml(yaml_str)
    assert result.is_valid, f"Errors: {result.errors}"
    assert result.parsed["scoring"]["recency_half_life_hours"] == 168
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_plan_engine.py::test_validate_austin_terror_watch_yaml -v`
Expected: FAIL — current value is 12, not 168.

- [ ] **Step 3: Edit austin-terror-watch.yaml**

In `plans/austin-terror-watch.yaml`, change line 109:

```yaml
  recency_half_life_hours: 168
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_plan_engine.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add plans/austin-terror-watch.yaml tests/test_plan_engine.py
git commit -m "fix(plans): increase austin-terror-watch recency half-life to 168h"
```

---

## Chunk 2: Config and NLP Enrichment Migration

### Task 4: Replace Ollama config with generic LLM settings

**Files:**
- Modify: `src/osint_core/config.py:30-32`

- [ ] **Step 1: Edit config.py — replace ollama settings**

In `src/osint_core/config.py`, replace lines 30-32:

```python
  # --- LLM inference ---
  llm_url: str = "http://vllm-inference.inference.svc.cluster.local:8000"
  llm_model: str = "meta-llama/Llama-3.2-3B-Instruct"
```

- [ ] **Step 2: Verify config loads**

Run: `python -c "from osint_core.config import settings; print(settings.llm_url, settings.llm_model)"`
Expected: prints the two default values.

- [ ] **Step 3: Commit**

```bash
git add src/osint_core/config.py
git commit -m "feat(config): replace ollama settings with generic llm_url/llm_model"
```

### Task 5: Rewrite nlp_enrich.py to use OpenAI-compatible API

**Files:**
- Modify: `src/osint_core/workers/nlp_enrich.py` (full file)
- Test: `tests/workers/test_nlp_enrich.py`

- [ ] **Step 1: Update test mocks for new API format**

Rewrite `tests/workers/test_nlp_enrich.py` — update function name references, URL, and response format:

```python
"""Tests for NLP enrichment task."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from osint_core.workers.nlp_enrich import _enrich_event_async


def _mock_engine():
    engine = MagicMock()
    engine.dispose = AsyncMock()
    return engine


def _mock_session(event):
    session = AsyncMock()
    session.get = AsyncMock(return_value=event)
    session.commit = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    return session


@pytest.mark.asyncio
async def test_skips_event_with_existing_nlp_data():
    event = MagicMock()
    event.nlp_relevance = "relevant"
    event.nlp_summary = "Already summarized"

    engine = _mock_engine()
    session = _mock_session(event)

    with patch("osint_core.workers.nlp_enrich.create_async_engine", return_value=engine), \
         patch("osint_core.workers.nlp_enrich.async_sessionmaker") as mock_sf:
        mock_sf.return_value = MagicMock(return_value=session)
        result = await _enrich_event_async("event-123")
        assert result["status"] == "skipped"


@pytest.mark.asyncio
async def test_generates_summary_for_empty():
    event = MagicMock()
    event.id = "event-123"
    event.title = "Bombing in downtown Austin"
    event.summary = None
    event.nlp_summary = None
    event.nlp_relevance = None
    event.plan_version = MagicMock()
    event.plan_version.content = {
        "enrichment": {"nlp_enabled": True, "mission": "Monitor terror threats in Austin"},
        "keywords": ["bombing", "attack"],
    }
    event.metadata_ = {}

    llm_response = {
        "summary": "A bombing incident occurred in downtown Austin.",
        "relevance": "relevant",
        "entities": [{"name": "Austin", "type": "location"}],
    }

    engine = _mock_engine()
    session = _mock_session(event)

    with patch("osint_core.workers.nlp_enrich.create_async_engine", return_value=engine), \
         patch("osint_core.workers.nlp_enrich.async_sessionmaker") as mock_sf, \
         patch("osint_core.workers.nlp_enrich._call_llm", return_value=llm_response):
        mock_sf.return_value = MagicMock(return_value=session)
        result = await _enrich_event_async("event-123")
        assert result["status"] == "enriched"
        assert event.nlp_summary == "A bombing incident occurred in downtown Austin."
        assert event.nlp_relevance == "relevant"


@pytest.mark.asyncio
async def test_fallback_on_llm_timeout():
    event = MagicMock()
    event.id = "event-123"
    event.title = "Some article"
    event.summary = None
    event.nlp_summary = None
    event.nlp_relevance = None
    event.plan_version = MagicMock()
    event.plan_version.content = {
        "enrichment": {"nlp_enabled": True, "mission": "test"},
        "keywords": [],
    }
    event.metadata_ = {}

    engine = _mock_engine()
    session = _mock_session(event)

    with patch("osint_core.workers.nlp_enrich.create_async_engine", return_value=engine), \
         patch("osint_core.workers.nlp_enrich.async_sessionmaker") as mock_sf, \
         patch("osint_core.workers.nlp_enrich._call_llm", side_effect=TimeoutError):
        mock_sf.return_value = MagicMock(return_value=session)
        result = await _enrich_event_async("event-123")
        assert result["status"] == "fallback"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/workers/test_nlp_enrich.py -v`
Expected: FAIL — `_call_llm` does not exist yet (still `_call_ollama`).

- [ ] **Step 3: Rewrite nlp_enrich.py**

Replace the full contents of `src/osint_core/workers/nlp_enrich.py`:

```python
"""NLP enrichment task using OpenAI-compatible LLM for summary, relevance, entities.

NOTE: This file is separate from enrich.py which contains vectorize_event_task
and correlate_event_task.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from osint_core.config import settings
from osint_core.models.event import Event
from osint_core.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_SYSTEM_MESSAGE = (
    "You are an intelligence analyst. Respond with JSON only.\n"
    'Respond with exactly this JSON structure:\n'
    '{"summary": "1-2 sentence English summary of the event",\n'
    '"relevance": "relevant|tangential|irrelevant",\n'
    '"entities": [{"name": "...", "type": "person|organization|location|indicator"}]}'
)

_USER_TEMPLATE = """Event title: {title}
Event metadata: {metadata}

Plan mission: {mission}
Plan keywords: {keywords}"""


async def _call_llm(system: str, user: str) -> dict[str, Any]:
    url = f"{settings.llm_url}/v1/chat/completions"
    payload = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"]
    result: dict[str, Any] = json.loads(raw)
    return result


async def _enrich_event_async(event_id: str) -> dict[str, Any]:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        event = await db.get(Event, event_id)
        if event is None:
            await engine.dispose()
            return {"event_id": event_id, "status": "not_found"}

        if event.nlp_relevance and event.nlp_summary:
            await engine.dispose()
            return {"event_id": event_id, "status": "skipped"}

        plan_content: dict[str, Any] = {}
        if event.plan_version:
            plan_content = event.plan_version.content or {}

        enrichment = plan_content.get("enrichment", {})
        if not enrichment.get("nlp_enabled", False):
            await engine.dispose()
            return {"event_id": event_id, "status": "nlp_disabled"}

        mission = enrichment.get("mission", "")
        keywords = plan_content.get("keywords", [])

        user_msg = _USER_TEMPLATE.format(
            title=event.title or "",
            metadata=json.dumps(event.metadata_ or {}, default=str)[:500],
            mission=mission,
            keywords=", ".join(keywords),
        )

        try:
            result = await _call_llm(_SYSTEM_MESSAGE, user_msg)
        except (TimeoutError, httpx.TimeoutException, httpx.HTTPError, json.JSONDecodeError) as e:
            logger.warning("NLP enrichment fallback for %s: %s", event_id, e)
            await engine.dispose()
            return {"event_id": event_id, "status": "fallback"}

        if not event.summary and result.get("summary"):
            event.nlp_summary = result["summary"]

        relevance = result.get("relevance", "")
        if relevance in ("relevant", "tangential", "irrelevant"):
            event.nlp_relevance = relevance

        await db.commit()

    await engine.dispose()
    return {"event_id": event_id, "status": "enriched"}


@celery_app.task(bind=True, name="osint.nlp_enrich_event", max_retries=1)  # type: ignore[untyped-decorator]
def nlp_enrich_task(self: Any, event_id: str) -> dict[str, Any]:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_enrich_event_async(event_id))
    except Exception as exc:
        logger.exception("NLP enrichment failed for %s", event_id)
        raise self.retry(
            exc=exc, countdown=min(2 ** self.request.retries * 30, 900)
        ) from exc
    finally:
        loop.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/workers/test_nlp_enrich.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/osint_core/workers/nlp_enrich.py tests/workers/test_nlp_enrich.py
git commit -m "feat(nlp): migrate nlp_enrich from Ollama to OpenAI-compatible API"
```

### Task 6: Rewrite brief_generator.py to use OpenAI-compatible API

**Files:**
- Modify: `src/osint_core/services/brief_generator.py` (rename ollama refs, rewrite generate method)
- Test: `tests/test_brief_generator.py`

- [ ] **Step 1: Update test fixtures and mocks**

In `tests/test_brief_generator.py`, make these changes:

1. Rename fixture `generator_no_ollama` → `generator_no_llm`, update constructor args:
```python
@pytest.fixture()
def generator_no_llm() -> BriefGenerator:
    """BriefGenerator with LLM explicitly disabled."""
    return BriefGenerator(llm_url="", llm_model="", llm_available=False)
```

2. Rename fixture `generator_with_ollama` → `generator_with_llm`, update constructor args:
```python
@pytest.fixture()
def generator_with_llm() -> BriefGenerator:
    """BriefGenerator pointing at a (mocked) LLM endpoint."""
    return BriefGenerator(
        llm_url="http://localhost:8000",
        llm_model="meta-llama/Llama-3.2-3B-Instruct",
        llm_available=True,
    )
```

3. Update `test_template_fallback_produces_markdown` — change param from `generator_no_ollama` to `generator_no_llm`.

4. Update `test_ollama_generation` → `test_llm_generation`:
```python
@respx.mock
@pytest.mark.asyncio
async def test_llm_generation(generator_with_llm: BriefGenerator):
    """BriefGenerator calls LLM API and returns the generated text."""
    llm_response = {
        "choices": [
            {
                "message": {
                    "content": "## Threat Summary\n\nCritical CVE activity detected."
                }
            }
        ],
    }

    respx.post("http://localhost:8000/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=llm_response)
    )

    result = await generator_with_llm.generate_from_llm(
        query="Summarize recent CVE activity",
        context="CVE-2026-1234 was published with CVSS 9.8",
    )

    assert "Threat Summary" in result
    assert "Critical CVE activity detected" in result
```

5. Update `test_ollama_fallback_on_error` → `test_llm_fallback_on_error`:
```python
@respx.mock
@pytest.mark.asyncio
async def test_llm_fallback_on_error(generator_with_llm: BriefGenerator):
    """When LLM returns an error, generate() falls back to template."""
    respx.post("http://localhost:8000/v1/chat/completions").mock(
        return_value=httpx.Response(500, json={"error": "model not found"})
    )

    result = await generator_with_llm.generate(
        query="Summarize threats",
        events=SAMPLE_EVENTS,
        indicators=SAMPLE_INDICATORS,
        entities=SAMPLE_ENTITIES,
    )

    assert "# Intel Brief:" in result
    assert "CVE-2026-1234 Published" in result
    assert "192.168.1.100" in result
```

6. Update `test_template_includes_events_indicators_entities` — change param from `generator_no_ollama` to `generator_no_llm`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_brief_generator.py -v`
Expected: FAIL — BriefGenerator constructor doesn't accept `llm_*` params yet.

- [ ] **Step 3: Rewrite brief_generator.py**

In `src/osint_core/services/brief_generator.py`, make these changes:

1. Update module docstring (line 1):
```python
"""Brief generator — produce intel briefs via LLM or Jinja2 template fallback."""
```

2. Rename class docstring and constructor (lines 29-48):
```python
class BriefGenerator:
    """Generate intelligence briefs using an OpenAI-compatible LLM or a Jinja2 template fallback.

    Args:
        llm_url: Base URL for the LLM API (e.g. ``http://vllm:8000``).
        llm_model: Model identifier (e.g. ``meta-llama/Llama-3.2-3B-Instruct``).
        llm_available: Whether to attempt LLM generation before falling back.
    """

    def __init__(
        self,
        *,
        llm_url: str = "",
        llm_model: str = "",
        llm_available: bool = True,
    ) -> None:
        self._llm_url = llm_url.rstrip("/") if llm_url else ""
        self._llm_model = llm_model
        self._llm_available = llm_available and bool(llm_url)
        self._template = _load_template()
```

3. Rename `generate_from_ollama` → `generate_from_llm` (lines 99-134) and rewrite to OpenAI format:
```python
    async def generate_from_llm(self, *, query: str, context: str) -> str:
        """Call an OpenAI-compatible chat completions endpoint to produce an AI brief.

        Args:
            query: The user's natural-language query describing the brief scope.
            context: Assembled context text (events, indicators, entities).

        Returns:
            Generated Markdown string from the LLM.

        Raises:
            httpx.HTTPStatusError: If the LLM API returns a non-2xx status.
            httpx.ConnectError: If the LLM service is unreachable.
        """
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self._llm_url}/v1/chat/completions",
                json={
                    "model": self._llm_model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": f"Query: {query}\n\nContext:\n{context}"},
                    ],
                },
            )
            response.raise_for_status()

        data = response.json()
        text: str = data["choices"][0]["message"]["content"]

        logger.info(
            "brief_generated_from_llm",
            model=self._llm_model,
            response_length=len(text),
        )
        return text
```

4. Update `generate()` method (lines 140-176) — change `self._ollama_available` to `self._llm_available`, change `generate_from_ollama` to `generate_from_llm`, update log message:
```python
        if self._llm_available:
            try:
                context = self._build_context(events, indicators, entities)
                return await self.generate_from_llm(query=query, context=context)
            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as exc:
                logger.warning(
                    "llm_generation_failed_falling_back_to_template",
                    error=str(exc),
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_brief_generator.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/osint_core/services/brief_generator.py tests/test_brief_generator.py
git commit -m "feat(briefs): migrate BriefGenerator from Ollama to OpenAI-compatible API"
```

### Task 7: Update briefs route, model default, docker-compose, and remaining test references

**Files:**
- Modify: `src/osint_core/api/routes/briefs.py:65-83`
- Modify: `src/osint_core/models/brief.py:32-33`
- Modify: `docker-compose.dev.yaml:37`
- Modify: `tests/test_api_routes.py:605`
- Modify: `tests/test_schemas.py:153,159`
- Modify: `tests/integration/test_pipeline.py:175,387`

- [ ] **Step 1: Update briefs.py route**

In `src/osint_core/api/routes/briefs.py`, change lines 65-83:

```python
    generator = BriefGenerator(
        llm_url=settings.llm_url,
        llm_model=settings.llm_model,
    )

    content_md = await generator.generate(
        query=body.query,
        events=[],
        indicators=[],
        entities=[],
    )

    brief = Brief(
        title=body.query,
        content_md=content_md,
        target_query=body.query,
        generated_by="llm",
        model_id=settings.llm_model,
        requested_by=current_user.username,
    )
```

- [ ] **Step 2: Update Brief model default**

In `src/osint_core/models/brief.py`, change lines 32-33:

```python
    generated_by: Mapped[str] = mapped_column(
        Text, default="llm", server_default="llm"
    )
```

Note: The initial migration (0001) has `server_default='ollama'` baked in. The model-level `server_default="llm"` won't retroactively change the DB column default for existing deployments, but it makes the code consistent. A follow-up migration to alter the column default can be done separately if needed.

- [ ] **Step 3: Update docker-compose.dev.yaml**

In `docker-compose.dev.yaml`, change line 37:

```yaml
      OSINT_LLM_URL: http://host.docker.internal:8000
```

- [ ] **Step 4: Update test_api_routes.py**

In `tests/test_api_routes.py`, change line 605:

```python
            generated_by="llm",
```

- [ ] **Step 5: Update test_schemas.py**

In `tests/test_schemas.py`, change line 153:

```python
        "generated_by": "llm",
```

And change line 159:

```python
    assert brief.generated_by == "llm"
```

- [ ] **Step 6: Update test_pipeline.py**

In `tests/integration/test_pipeline.py`, change lines 175 and 387:

```python
    generator = BriefGenerator(llm_available=False)
```

(Both occurrences.)

- [ ] **Step 7: Run all affected tests**

Run: `pytest tests/test_api_routes.py tests/test_brief_generator.py tests/test_schemas.py tests/integration/test_pipeline.py tests/workers/test_nlp_enrich.py -v`
Expected: ALL PASS.

- [ ] **Step 8: Commit**

```bash
git add src/osint_core/api/routes/briefs.py src/osint_core/models/brief.py docker-compose.dev.yaml tests/test_api_routes.py tests/test_schemas.py tests/integration/test_pipeline.py
git commit -m "feat(briefs): update briefs route, model default, docker-compose, and tests for llm migration"
```

---

## Chunk 3: Celery Configuration Fix

### Task 8: Add nlp_enrich to Celery include and task routes

**Files:**
- Modify: `src/osint_core/workers/celery_app.py:18-43`

- [ ] **Step 1: Edit celery_app.py**

In `src/osint_core/workers/celery_app.py`:

Add to `include` list (after line 23):
```python
        "osint_core.workers.nlp_enrich",
```

Add to `task_routes` dict (after line 39):
```python
        "osint_core.workers.nlp_enrich.*": {"queue": "enrich"},
```

- [ ] **Step 2: Verify the module loads**

Run: `python -c "from osint_core.workers.celery_app import celery_app; print('nlp_enrich' in str(celery_app.conf.include))"`
Expected: `True`

- [ ] **Step 3: Run full test suite**

Run: `pytest tests/ -v --ignore=tests/integration -x`
Expected: ALL PASS. This is the final validation that all changes work together.

- [ ] **Step 4: Commit**

```bash
git add src/osint_core/workers/celery_app.py
git commit -m "fix(celery): add nlp_enrich to include list and task routes"
```

### Task 9: Push and verify PR

- [ ] **Step 1: Push all commits**

```bash
git push origin fix/idempotent-migrations
```

- [ ] **Step 2: Verify PR status**

```bash
gh pr view 39 --json title,state,commits --jq '{title, state, commit_count: (.commits | length)}'
```
