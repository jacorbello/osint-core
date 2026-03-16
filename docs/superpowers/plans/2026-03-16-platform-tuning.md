# OSINT Platform Tuning Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Overhaul scoring, filtering, enrichment, alerting, sources, and dedup to produce accurate, actionable intelligence from the OSINT platform.

**Architecture:** Rebuild scoring as a 0-1 normalized relevance score with signal-based severity promotions. Insert NLP enrichment (Ollama) between ingest and scoring. Add near-dedup via SimHash, multi-channel alert routing, and 5 new source connectors. All changes follow existing Celery/SQLAlchemy/FastAPI patterns.

**Tech Stack:** Python 3.12, FastAPI, Celery, SQLAlchemy 2.0 (async), PostgreSQL, Qdrant, Ollama/LLaMA 3.1:8b, httpx, pytest

**Spec:** `docs/superpowers/specs/2026-03-16-platform-tuning-design.md`

---

## Chunk 1: Database Migrations & Scoring Overhaul

### Task 1: Alembic Migration — New Event Columns

**Files:**
- Modify: `src/osint_core/models/event.py`
- Create: `migrations/versions/xxxx_add_scoring_columns.py` (via alembic)

- [ ] **Step 1: Add new columns to Event model**

In `src/osint_core/models/event.py`, add after `metadata_` column (~line 130):

```python
    simhash: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    canonical_event_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("events.id"), nullable=True,
    )
    corroboration_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    nlp_relevance: Mapped[str | None] = mapped_column(Text, nullable=True)
    nlp_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
```

Add import for `BigInteger, Integer` from sqlalchemy if not present.

- [ ] **Step 2: Generate alembic migration**

Run: `cd /Users/jacorbello/repos/osint-core && alembic revision --autogenerate -m "add scoring columns: simhash, canonical_event_id, corroboration_count, nlp_relevance, nlp_summary"`

Verify the generated migration adds the 5 columns and the index on `simhash`.

- [ ] **Step 3: Commit**

```bash
git add src/osint_core/models/event.py migrations/
git commit -m "feat(models): add simhash, canonical_event_id, corroboration, NLP columns to Event"
```

---

### Task 2: Rewrite Scoring Formula

**Files:**
- Modify: `src/osint_core/services/scoring.py`
- Create: `tests/services/test_scoring_v3.py`

- [ ] **Step 1: Write failing tests for new scoring formula**

Create `tests/services/test_scoring_v3.py`:

```python
"""Tests for the new normalized 0-1 scoring formula."""
import pytest
from datetime import datetime, timezone, timedelta
from osint_core.services.scoring import (
    ScoringConfig,
    score_event,
    score_to_severity,
    compute_keyword_relevance,
    compute_geographic_relevance,
)


def _now():
    return datetime.now(timezone.utc)


class TestKeywordRelevance:
    def test_no_keywords_configured_returns_one(self):
        config = ScoringConfig(recency_half_life_hours=24, keywords=[])
        assert compute_keyword_relevance(0, 0, config) == 1.0

    def test_no_matches_returns_low_score(self):
        config = ScoringConfig(recency_half_life_hours=24, keywords=["terror", "attack", "bomb"])
        assert compute_keyword_relevance(0, 3, config) == pytest.approx(0.05)

    def test_all_keywords_matched_returns_one(self):
        config = ScoringConfig(recency_half_life_hours=24, keywords=["terror", "attack"])
        assert compute_keyword_relevance(2, 2, config) == pytest.approx(1.0)

    def test_partial_match(self):
        config = ScoringConfig(recency_half_life_hours=24, keywords=["a", "b", "c", "d"])
        result = compute_keyword_relevance(2, 4, config)
        assert 0.0 < result < 1.0

    def test_nlp_relevant_overrides(self):
        config = ScoringConfig(recency_half_life_hours=24, keywords=["a", "b"])
        assert compute_keyword_relevance(0, 2, config, nlp_relevance="relevant") == 1.0

    def test_nlp_tangential_overrides(self):
        config = ScoringConfig(recency_half_life_hours=24, keywords=["a", "b"])
        assert compute_keyword_relevance(0, 2, config, nlp_relevance="tangential") == 0.4

    def test_nlp_irrelevant_overrides(self):
        config = ScoringConfig(recency_half_life_hours=24, keywords=["a", "b"])
        assert compute_keyword_relevance(0, 2, config, nlp_relevance="irrelevant") == 0.05


class TestGeographicRelevance:
    def test_no_target_geo_returns_one(self):
        assert compute_geographic_relevance(None, None, None, target_geo=None) == 1.0

    def test_exact_country_match(self):
        result = compute_geographic_relevance(
            country_code="USA", lat=None, lon=None,
            target_geo={"country_codes": ["USA"]},
        )
        assert result == 1.0

    def test_wrong_country(self):
        result = compute_geographic_relevance(
            country_code="CHN", lat=None, lon=None,
            target_geo={"country_codes": ["USA"]},
        )
        assert result == 0.2

    def test_no_geo_data_benefit_of_doubt(self):
        result = compute_geographic_relevance(
            country_code=None, lat=None, lon=None,
            target_geo={"country_codes": ["USA"]},
        )
        assert result == 0.7

    def test_within_radius(self):
        # Austin TX: 30.2672, -97.7431
        result = compute_geographic_relevance(
            country_code="USA", lat=30.27, lon=-97.74,
            target_geo={"lat": 30.2672, "lon": -97.7431, "radius_km": 50},
        )
        assert result == 1.0

    def test_within_2x_radius(self):
        # Houston TX: 29.7604, -95.3698 (~240km from Austin)
        result = compute_geographic_relevance(
            country_code="USA", lat=29.76, lon=-95.37,
            target_geo={"lat": 30.2672, "lon": -97.7431, "radius_km": 150},
        )
        assert result == 0.7

    def test_same_country_beyond_2x_radius(self):
        # New York: 40.7128, -74.0060 (~2700km from Austin)
        result = compute_geographic_relevance(
            country_code="USA", lat=40.71, lon=-74.01,
            target_geo={"lat": 30.2672, "lon": -97.7431, "radius_km": 150, "country_codes": ["USA"]},
        )
        assert result == 0.5


class TestScoreEvent:
    def test_fresh_relevant_event_scores_high(self):
        config = ScoringConfig(
            recency_half_life_hours=12,
            keywords=["terror", "attack"],
            source_reputation={"cisa_kev": 1.0},
        )
        score = score_event(
            source_id="cisa_kev",
            occurred_at=_now(),
            indicator_count=0,
            matched_keywords=2,
            total_keywords=2,
            config=config,
        )
        assert 0.9 <= score <= 1.0

    def test_old_event_decays(self):
        config = ScoringConfig(
            recency_half_life_hours=12,
            keywords=[],
            source_reputation={"src": 1.0},
        )
        score = score_event(
            source_id="src",
            occurred_at=_now() - timedelta(hours=24),
            indicator_count=0,
            matched_keywords=0,
            total_keywords=0,
            config=config,
        )
        # 2 half-lives = 0.25 decay
        assert 0.2 <= score <= 0.3

    def test_decay_floor(self):
        config = ScoringConfig(
            recency_half_life_hours=12,
            keywords=[],
            source_reputation={"src": 1.0},
        )
        score = score_event(
            source_id="src",
            occurred_at=_now() - timedelta(hours=1000),
            indicator_count=0,
            matched_keywords=0,
            total_keywords=0,
            config=config,
        )
        assert score >= 0.1 * 0.5  # floor * source_trust minimum

    def test_unknown_source_defaults_half(self):
        config = ScoringConfig(
            recency_half_life_hours=12,
            keywords=[],
            source_reputation={},
        )
        score = score_event(
            source_id="unknown",
            occurred_at=_now(),
            indicator_count=0,
            matched_keywords=0,
            total_keywords=0,
            config=config,
        )
        assert 0.45 <= score <= 0.55

    def test_score_clamped_to_one(self):
        config = ScoringConfig(
            recency_half_life_hours=12,
            keywords=["a"],
            source_reputation={"src": 1.0},
        )
        # Even with corroboration, should not exceed 1.0
        score = score_event(
            source_id="src",
            occurred_at=_now(),
            indicator_count=0,
            matched_keywords=1,
            total_keywords=1,
            config=config,
            corroboration_count=5,
        )
        assert score <= 1.0


class TestScoreToSeverity:
    def test_info(self):
        assert score_to_severity(0.1) == "info"

    def test_low(self):
        assert score_to_severity(0.3) == "low"

    def test_medium(self):
        assert score_to_severity(0.6) == "medium"

    def test_high(self):
        assert score_to_severity(0.8) == "high"

    def test_boundary_low_medium(self):
        assert score_to_severity(0.5) == "medium"

    def test_boundary_medium_high(self):
        assert score_to_severity(0.75) == "high"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jacorbello/repos/osint-core && python -m pytest tests/services/test_scoring_v3.py -v`
Expected: ImportError / failures (functions don't exist yet or have wrong signatures)

- [ ] **Step 3: Rewrite scoring.py with new formula**

Replace `src/osint_core/services/scoring.py` entirely:

```python
"""Scoring engine for OSINT events.

Formula:
    relevance_score = keyword_relevance * geographic_relevance * source_trust
    recency_factor = max(0.1, 0.5^(hours_old / half_life))
    boosted = relevance_score * corroboration_bonus
    final_score = min(1.0, boosted * recency_factor)

Severity thresholds (from final_score):
    0.0-0.2  -> info
    0.2-0.5  -> low
    0.5-0.75 -> medium
    0.75-1.0 -> high
    (critical is signal-promoted only)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ScoringConfig:
    recency_half_life_hours: float
    source_reputation: dict[str, float] = field(default_factory=dict)
    ioc_match_boost: float = 1.0
    keywords: list[str] = field(default_factory=list)
    keyword_miss_penalty: float = 0.05
    target_geo: dict | None = None


NLP_RELEVANCE_MAP: dict[str, float] = {
    "relevant": 1.0,
    "tangential": 0.4,
    "irrelevant": 0.05,
}


def match_keywords(text: str, keywords: list[str]) -> list[str]:
    """Case-insensitive substring match of keywords against text."""
    if not text or not keywords:
        return []
    lower = text.lower()
    return [kw for kw in keywords if kw.lower() in lower]


def compute_keyword_relevance(
    matched_count: int,
    total_keywords: int,
    config: ScoringConfig,
    nlp_relevance: str | None = None,
) -> float:
    """Compute keyword relevance factor (0.0-1.0).

    If NLP classification is available, it overrides keyword matching.
    """
    if nlp_relevance and nlp_relevance in NLP_RELEVANCE_MAP:
        return NLP_RELEVANCE_MAP[nlp_relevance]
    if total_keywords == 0:
        return 1.0
    if matched_count == 0:
        return config.keyword_miss_penalty
    return matched_count / total_keywords


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in km."""
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def compute_geographic_relevance(
    country_code: str | None,
    lat: float | None,
    lon: float | None,
    target_geo: dict | None,
) -> float:
    """Compute geographic relevance factor (0.0-1.0)."""
    if target_geo is None:
        return 1.0

    target_countries = target_geo.get("country_codes", [])
    target_lat = target_geo.get("lat")
    target_lon = target_geo.get("lon")
    radius_km = target_geo.get("radius_km")

    # Lat/lon radius check takes precedence when available
    if (
        lat is not None
        and lon is not None
        and target_lat is not None
        and target_lon is not None
        and radius_km is not None
    ):
        dist = _haversine_km(lat, lon, target_lat, target_lon)
        if dist <= radius_km:
            return 1.0
        if dist <= radius_km * 2:
            return 0.7
        # Beyond 2x radius but same country
        if country_code and country_code in target_countries:
            return 0.5
        if country_code:
            return 0.2
        return 0.7  # no country info

    # Country-only check
    if not country_code and not lat:
        return 0.7  # benefit of doubt
    if country_code and target_countries and country_code in target_countries:
        return 1.0
    if country_code and target_countries:
        return 0.2

    return 0.7


def score_event(
    source_id: str,
    occurred_at: datetime | None,
    indicator_count: int,
    matched_keywords: int,
    total_keywords: int,
    config: ScoringConfig,
    *,
    country_code: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    nlp_relevance: str | None = None,
    corroboration_count: int = 0,
) -> float:
    """Score an event on a 0.0-1.0 scale."""
    source_trust = config.source_reputation.get(source_id, 0.5)

    keyword_rel = compute_keyword_relevance(
        matched_keywords, total_keywords, config, nlp_relevance=nlp_relevance,
    )

    geo_rel = compute_geographic_relevance(
        country_code, lat, lon, config.target_geo,
    )

    relevance = keyword_rel * geo_rel * source_trust

    # Corroboration bonus (capped at 1.5x)
    if corroboration_count > 0:
        bonus = min(1.5, 1.0 + 0.2 * corroboration_count)
        relevance *= bonus

    # Recency decay with floor
    if occurred_at is not None:
        now = datetime.now(timezone.utc)
        hours_old = max(0.0, (now - occurred_at).total_seconds() / 3600)
        recency = max(0.1, 0.5 ** (hours_old / config.recency_half_life_hours))
    else:
        recency = 0.5  # unknown time, middle ground

    return min(1.0, relevance * recency)


def score_to_severity(score: float) -> str:
    """Map a 0.0-1.0 score to severity label."""
    if score >= 0.75:
        return "high"
    if score >= 0.5:
        return "medium"
    if score >= 0.2:
        return "low"
    return "info"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/jacorbello/repos/osint-core && python -m pytest tests/services/test_scoring_v3.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/osint_core/services/scoring.py tests/services/test_scoring_v3.py
git commit -m "feat(scoring): rewrite formula with 0-1 normalization, geographic relevance, NLP override"
```

---

### Task 3: Update Score Worker to Use New Formula

**Files:**
- Modify: `src/osint_core/workers/score.py`
- Modify: `tests/workers/test_score.py`

- [ ] **Step 1: Write failing test for updated score worker**

Add to `tests/workers/test_score.py`:

```python
def test_score_event_uses_new_formula(mock_db_session, monkeypatch):
    """Score should be in 0-1 range with new formula."""
    event = _make_event(
        source_id="cisa_kev",
        occurred_at=datetime.now(timezone.utc),
    )
    plan_content = {
        "scoring": {
            "recency_half_life_hours": 12,
            "source_reputation": {"cisa_kev": 1.0},
            "keywords": ["vulnerability"],
        },
    }
    # ... mock setup for plan lookup
    result = _score_event_async(event.id)
    assert 0.0 <= result["score"] <= 1.0
    assert result["severity"] in ("info", "low", "medium", "high")
```

- [ ] **Step 2: Update `_build_scoring_config` in score.py**

Update `_build_scoring_config` to pass `target_geo` from plan content:

```python
def _build_scoring_config(plan_content: dict) -> ScoringConfig:
    scoring = plan_content.get("scoring", {})
    parent_scoring = plan_content.get("defaults", {}).get("scoring", {})
    return ScoringConfig(
        recency_half_life_hours=_resolve(scoring, parent_scoring, "recency_half_life_hours", 24),
        source_reputation=_resolve(scoring, parent_scoring, "source_reputation", {}),
        ioc_match_boost=_resolve(scoring, parent_scoring, "ioc_match_boost", 1.0),
        keywords=plan_content.get("keywords", []),
        keyword_miss_penalty=_resolve(scoring, parent_scoring, "keyword_miss_penalty", 0.05),
        target_geo=plan_content.get("target_geo"),
    )
```

- [ ] **Step 3: Update `_score_event_async` to pass new parameters**

In the scoring call inside `_score_event_async`, update to:

```python
matched = match_keywords(
    f"{event.title or ''} {event.summary or ''} {event.nlp_summary or ''}",
    scoring_cfg.keywords,
)
raw_score = score_event(
    source_id=event.source_id,
    occurred_at=event.occurred_at,
    indicator_count=len(event.indicators),
    matched_keywords=len(matched),
    total_keywords=len(scoring_cfg.keywords),
    config=scoring_cfg,
    country_code=event.country_code,
    lat=event.latitude,
    lon=event.longitude,
    nlp_relevance=event.nlp_relevance,
    corroboration_count=event.corroboration_count,
)
severity = score_to_severity(raw_score)
```

- [ ] **Step 4: Update severity promotion evaluation**

Add after severity computation in `_score_event_async`:

```python
severity = _apply_promotions(event, severity, plan_content)
```

New helper function:

```python
def _apply_promotions(event, base_severity: str, plan_content: dict) -> str:
    """Evaluate severity promotion rules. Promotions only elevate, never downgrade."""
    promotions = plan_content.get("scoring", {}).get("severity_promotions", [])
    best = base_severity
    for rule in promotions:
        cond = rule.get("condition", {})
        target = rule.get("promote_to", base_severity)
        if _evaluate_condition(event, cond) and _severity_gte(target, best):
            best = target
    return best


def _evaluate_condition(event, condition: dict) -> bool:
    """Evaluate a single promotion condition against an event."""
    field = condition.get("field", "")
    op = condition.get("op", "eq")
    value = condition.get("value")

    actual = _get_field_value(event, field)
    if actual is None:
        return False

    if op == "eq":
        return actual == value
    if op == "neq":
        return actual != value
    if op == "gte":
        return actual >= value
    if op == "lte":
        return actual <= value
    if op == "gt":
        return actual > value
    if op == "lt":
        return actual < value
    if op == "contains":
        return str(value).lower() in str(actual).lower()
    if op == "in":
        return actual in value
    return False


def _get_field_value(event, field: str):
    """Resolve dotted field path against event and its relations."""
    if field == "source_id":
        return event.source_id
    if field == "source_category":
        return event.source_category
    if field == "country_code":
        return event.country_code
    if field == "event_type":
        return event.event_type
    if field == "severity":
        return event.severity
    if field == "fatalities":
        return getattr(event, "fatalities", None)
    if field.startswith("indicators."):
        subfield = field.split(".", 1)[1]
        for ind in event.indicators:
            val = getattr(ind, subfield, None) or (ind.metadata_ or {}).get(subfield)
            if val is not None:
                return val
    return None
```

- [ ] **Step 5: Fix existing score tests for new formula**

Update test expectations in `tests/workers/test_score.py` to expect 0-1 scores and new severity labels. The high-reputation mock values need to produce scores within the new thresholds.

- [ ] **Step 6: Run all score tests**

Run: `cd /Users/jacorbello/repos/osint-core && python -m pytest tests/workers/test_score.py tests/services/test_scoring_v3.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/osint_core/workers/score.py tests/workers/test_score.py
git commit -m "feat(score-worker): wire new scoring formula with geo, NLP, promotions"
```

---

### Task 4: Update Plan YAMLs — Rescale Source Reputation & Add Target Geo

**Files:**
- Modify: `plans/austin-terror-watch.yaml`
- Modify: `plans/cyber-threat-intel.yaml`
- Modify: `plans/humanitarian-intel.yaml`
- Modify: `plans/cortech-osint-master.yaml`

- [ ] **Step 1: Rescale source_reputation values (divide by 1.5) and add target_geo + severity_promotions**

`austin-terror-watch.yaml` changes:
```yaml
# source_reputation rescaled: 0.8->0.53, 1.0->0.67, 1.2->0.8, 1.5->1.0
scoring:
  source_reputation:
    gdelt_austin_terror: 0.53
    reliefweb_us: 0.67
    austin_statesman: 0.8
    kxan_news: 0.8
    fbi_press: 1.0

target_geo:
  country_codes: ["USA"]
  lat: 30.2672
  lon: -97.7431
  radius_km: 100

enrichment:
  nlp_enabled: true
  mission: "Monitor terrorism, extremism, and mass violence threats in the Austin, Texas metropolitan area"
  classify_relevance: true
  extract_entities: true
  generate_summaries: true
```

`cyber-threat-intel.yaml` changes:
```yaml
# source_reputation rescaled: 1.3->0.87, 1.0->0.67, 0.9->0.6, 1.1->0.73, 1.2->0.8, 0.8->0.53
scoring:
  source_reputation:
    cisa_kev: 0.87
    nvd_recent: 0.67
    osv_pypi: 0.6
    urlhaus_recent: 0.73
    threatfox_iocs: 0.8
    rss_hackernews: 0.53
  severity_promotions:
    - condition: {field: "indicators.cvss", op: "gte", value: 9.0}
      promote_to: critical
    - condition: {field: "source_id", op: "eq", value: "cisa_kev"}
      promote_to: high

enrichment:
  nlp_enabled: true
  mission: "Track vulnerabilities, malware campaigns, and IOC indicators affecting enterprise infrastructure"
  classify_relevance: true
  extract_entities: true
  generate_summaries: true
```

`humanitarian-intel.yaml` changes:
```yaml
# source_reputation rescaled: 1.0->0.67, 1.2->0.8
scoring:
  source_reputation:
    reliefweb: 0.67
    hrw_news: 0.8
    amnesty: 0.8

enrichment:
  nlp_enabled: true
  mission: "Monitor humanitarian crises, human rights violations, and disaster events globally"
  classify_relevance: true
  extract_entities: true
  generate_summaries: true
```

- [ ] **Step 2: Remove deprecated `weight` field from all plan source entries**

Remove `weight: X.X` lines from all source definitions in all plan YAMLs.

- [ ] **Step 3: Commit**

```bash
git add plans/
git commit -m "feat(plans): rescale source_reputation to 0-1, add target_geo, enrichment, severity_promotions"
```

---

## Chunk 2: GDELT Connector Filtering & Connector Improvements

### Task 5: GDELT Connector — Query Tightening & Geo Extraction

**Files:**
- Modify: `src/osint_core/connectors/gdelt.py`
- Create: `tests/connectors/test_gdelt_filtering.py`

- [ ] **Step 1: Write failing test for geo_terms and preferred_languages**

```python
"""Tests for GDELT connector filtering enhancements."""
import pytest
import httpx
import respx
from osint_core.connectors.gdelt import GdeltConnector
from osint_core.connectors.base import SourceConfig


@respx.mock
@pytest.mark.asyncio
async def test_geo_terms_appended_to_query():
    cfg = SourceConfig(
        id="test", type="gdelt_api",
        url="https://api.gdeltproject.org/api/v2/doc/doc",
        weight=1.0,
        extra={
            "query": "terrorism OR attack",
            "geo_terms": "Austin OR Texas",
            "mode": "ArtList",
            "maxrecords": "100",
        },
    )
    route = respx.get(cfg.url).mock(return_value=httpx.Response(200, json={"articles": []}))
    conn = GdeltConnector(cfg)
    await conn.fetch()
    called_params = dict(route.calls[0].request.url.params)
    assert "(terrorism OR attack) AND (Austin OR Texas)" in called_params.get("query", "")


@respx.mock
@pytest.mark.asyncio
async def test_preferred_languages_in_query():
    cfg = SourceConfig(
        id="test", type="gdelt_api",
        url="https://api.gdeltproject.org/api/v2/doc/doc",
        weight=1.0,
        extra={
            "query": "terrorism",
            "preferred_languages": ["English", "Spanish"],
            "mode": "ArtList",
            "maxrecords": "100",
        },
    )
    route = respx.get(cfg.url).mock(return_value=httpx.Response(200, json={"articles": []}))
    conn = GdeltConnector(cfg)
    await conn.fetch()
    called_params = dict(route.calls[0].request.url.params)
    q = called_params.get("query", "")
    assert "sourcelang:english" in q.lower() or "sourcelang:English" in q


@respx.mock
@pytest.mark.asyncio
async def test_extracts_country_code_from_sourcecountry():
    cfg = SourceConfig(
        id="test", type="gdelt_api",
        url="https://api.gdeltproject.org/api/v2/doc/doc",
        weight=1.0,
        extra={"query": "test", "mode": "ArtList", "maxrecords": "100"},
    )
    respx.get(cfg.url).mock(return_value=httpx.Response(200, json={"articles": [
        {
            "url": "https://example.com/article",
            "title": "Test Article",
            "seendate": "20260316T120000Z",
            "sourcecountry": "United States",
            "language": "English",
            "domain": "example.com",
        },
    ]}))
    conn = GdeltConnector(cfg)
    items = await conn.fetch()
    assert len(items) == 1
    assert items[0].country_code == "USA"


@respx.mock
@pytest.mark.asyncio
async def test_max_per_domain_cap():
    cfg = SourceConfig(
        id="test", type="gdelt_api",
        url="https://api.gdeltproject.org/api/v2/doc/doc",
        weight=1.0,
        extra={"query": "test", "mode": "ArtList", "maxrecords": "100", "max_per_domain": 2},
    )
    articles = [
        {"url": f"https://spam.com/a{i}", "title": f"Spam {i}", "seendate": "20260316T120000Z",
         "sourcecountry": "United States", "language": "English", "domain": "spam.com"}
        for i in range(10)
    ]
    respx.get(cfg.url).mock(return_value=httpx.Response(200, json={"articles": articles}))
    conn = GdeltConnector(cfg)
    items = await conn.fetch()
    assert len(items) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/jacorbello/repos/osint-core && python -m pytest tests/connectors/test_gdelt_filtering.py -v`

- [ ] **Step 3: Update GDELT connector**

Replace `src/osint_core/connectors/gdelt.py`:

```python
"""GDELT DOC 2.0 API connector with geographic and language filtering."""
from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime, timezone

import httpx

from .base import BaseConnector, RawItem

# Common GDELT country names to ISO-3 codes
_COUNTRY_MAP: dict[str, str] = {
    "United States": "USA", "United Kingdom": "GBR", "China": "CHN",
    "Russia": "RUS", "France": "FRA", "Germany": "DEU", "Japan": "JPN",
    "South Korea": "KOR", "India": "IND", "Brazil": "BRA", "Canada": "CAN",
    "Australia": "AUS", "Mexico": "MEX", "Spain": "ESP", "Italy": "ITA",
    "Turkey": "TUR", "Iran": "IRN", "Iraq": "IRQ", "Israel": "ISR",
    "Ukraine": "UKR", "Poland": "POL", "Nigeria": "NGA", "Egypt": "EGY",
    "Saudi Arabia": "SAU", "Pakistan": "PAK", "Indonesia": "IDN",
    "Argentina": "ARG", "Colombia": "COL", "South Africa": "ZAF",
    "Thailand": "THA", "Vietnam": "VNM", "Philippines": "PHL",
    "Taiwan": "TWN", "Netherlands": "NLD", "Belgium": "BEL",
    "Sweden": "SWE", "Norway": "NOR", "Denmark": "DNK", "Finland": "FIN",
    "Switzerland": "CHE", "Austria": "AUT", "Ireland": "IRL",
    "Portugal": "PRT", "Greece": "GRC", "Czech Republic": "CZE",
    "Romania": "ROU", "Hungary": "HUN", "Syria": "SYR", "Yemen": "YEM",
    "Afghanistan": "AFG", "Belarus": "BLR", "Georgia": "GEO",
    "Singapore": "SGP", "Malaysia": "MYS", "Chile": "CHL", "Peru": "PER",
}


class GdeltConnector(BaseConnector):
    async def fetch(self) -> list[RawItem]:
        query = self._build_query()
        params = {
            "query": query,
            "mode": self.config.extra.get("mode", "ArtList"),
            "maxrecords": str(self.config.extra.get("maxrecords", "100")),
            "format": "json",
        }
        timespan = self.config.extra.get("timespan")
        if timespan:
            params["timespan"] = timespan

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(self.config.url, params=params)
            resp.raise_for_status()

        data = resp.json()
        articles = data.get("articles", [])

        max_per_domain = self.config.extra.get("max_per_domain")
        if max_per_domain:
            articles = self._cap_per_domain(articles, max_per_domain)

        max_items = self.config.extra.get("max_items", 100)
        articles = articles[:max_items]

        return [self._parse_article(a) for a in articles if a.get("title")]

    def _build_query(self) -> str:
        base = self.config.extra.get("query", "")
        geo_terms = self.config.extra.get("geo_terms")
        langs = self.config.extra.get("preferred_languages", [])

        query = base
        if geo_terms:
            query = f"({base}) AND ({geo_terms})"

        if langs:
            lang_parts = " OR ".join(f"sourcelang:{lang}" for lang in langs)
            query = f"({query}) AND ({lang_parts})"

        return query

    def _cap_per_domain(self, articles: list[dict], cap: int) -> list[dict]:
        counts: Counter[str] = Counter()
        result = []
        for article in articles:
            domain = article.get("domain", "")
            if counts[domain] < cap:
                result.append(article)
                counts[domain] += 1
        return result

    def _parse_article(self, article: dict) -> RawItem:
        seen = article.get("seendate", "")
        occurred_at = None
        if seen:
            try:
                occurred_at = datetime.strptime(seen, "%Y%m%dT%H%M%SZ").replace(
                    tzinfo=timezone.utc,
                )
            except ValueError:
                pass

        country_name = article.get("sourcecountry", "")
        country_code = _COUNTRY_MAP.get(country_name)

        return RawItem(
            title=article.get("title", ""),
            url=article.get("url", ""),
            raw_data=article,
            source_category="geopolitical",
            occurred_at=occurred_at,
            country_code=country_code,
        )

    def dedupe_key(self, item: RawItem) -> str:
        url_hash = hashlib.sha256(item.url.encode()).hexdigest()[:16]
        return f"gdelt:{url_hash}"
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/jacorbello/repos/osint-core && python -m pytest tests/connectors/test_gdelt_filtering.py tests/connectors/test_gdelt.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/osint_core/connectors/gdelt.py tests/connectors/test_gdelt_filtering.py
git commit -m "feat(gdelt): add geo_terms, preferred_languages, country extraction, domain cap"
```

---

### Task 6: Connector Base — Max Items Cap & Content Threshold

**Files:**
- Modify: `src/osint_core/connectors/base.py`
- Modify: `src/osint_core/workers/ingest.py`

- [ ] **Step 1: Add `max_items` enforcement in ingest worker**

In `_ingest_source_async`, after `items = await connector.fetch()`:

```python
max_items = source_cfg.extra.get("max_items", 100)
items = items[:max_items]
# Skip items with no usable content
items = [i for i in items if i.title or i.summary]
```

- [ ] **Step 2: Run existing ingest tests**

Run: `cd /Users/jacorbello/repos/osint-core && python -m pytest tests/workers/test_ingest.py -v`

- [ ] **Step 3: Commit**

```bash
git add src/osint_core/workers/ingest.py
git commit -m "feat(ingest): enforce max_items cap and minimum content threshold"
```

---

## Chunk 3: NLP Enrichment Pipeline

### Task 7: NLP Enrich Celery Task

**Files:**
- Create: `src/osint_core/workers/enrich.py`
- Create: `tests/workers/test_enrich.py`

- [ ] **Step 1: Write failing tests**

Create `tests/workers/test_enrich.py`:

```python
"""Tests for NLP enrichment task."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from osint_core.workers.enrich import _enrich_event_async


@pytest.mark.asyncio
async def test_skips_event_with_existing_nlp_data(mock_db_session):
    """Events already enriched should be skipped."""
    event = MagicMock()
    event.nlp_relevance = "relevant"
    event.nlp_summary = "Already summarized"
    event.summary = "Has summary"
    mock_db_session.get = AsyncMock(return_value=event)

    result = await _enrich_event_async("event-123")
    assert result["status"] == "skipped"


@pytest.mark.asyncio
async def test_generates_summary_for_empty(mock_db_session):
    """Events with empty summary should get NLP summary."""
    event = MagicMock()
    event.id = "event-123"
    event.title = "Bombing in downtown Austin"
    event.summary = None
    event.nlp_summary = None
    event.nlp_relevance = None
    event.plan_version = MagicMock()
    event.plan_version.content = {
        "enrichment": {
            "nlp_enabled": True,
            "mission": "Monitor terror threats in Austin",
        },
        "keywords": ["bombing", "attack"],
    }
    mock_db_session.get = AsyncMock(return_value=event)

    ollama_response = {
        "summary": "A bombing incident occurred in downtown Austin.",
        "relevance": "relevant",
        "entities": [{"name": "Austin", "type": "location"}],
    }

    with patch("osint_core.workers.enrich._call_ollama", return_value=ollama_response):
        result = await _enrich_event_async("event-123")

    assert result["status"] == "enriched"
    assert event.nlp_summary == "A bombing incident occurred in downtown Austin."
    assert event.nlp_relevance == "relevant"


@pytest.mark.asyncio
async def test_fallback_on_ollama_timeout(mock_db_session):
    """If Ollama times out, enrichment should be skipped gracefully."""
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
    mock_db_session.get = AsyncMock(return_value=event)

    with patch("osint_core.workers.enrich._call_ollama", side_effect=TimeoutError):
        result = await _enrich_event_async("event-123")

    assert result["status"] == "fallback"
```

- [ ] **Step 2: Run tests to verify failure**

Run: `cd /Users/jacorbello/repos/osint-core && python -m pytest tests/workers/test_enrich.py -v`

- [ ] **Step 3: Implement enrich worker**

Create `src/osint_core/workers/enrich.py`:

```python
"""NLP enrichment task using Ollama/LLaMA for summary, relevance, entities."""
from __future__ import annotations

import asyncio
import json
import logging

import httpx
from celery import shared_task

from osint_core.config import get_settings

logger = logging.getLogger(__name__)

_ENRICH_PROMPT = """You are an intelligence analyst. Given this event, respond with JSON only.

Event title: {title}
Event metadata: {metadata}

Plan mission: {mission}
Plan keywords: {keywords}

Respond with exactly this JSON structure:
{{"summary": "1-2 sentence English summary of the event", "relevance": "relevant|tangential|irrelevant", "entities": [{{"name": "...", "type": "person|organization|location|indicator"}}]}}
"""


async def _call_ollama(prompt: str) -> dict:
    """Call Ollama API with timeout."""
    settings = get_settings()
    url = f"{settings.OSINT_OLLAMA_URL}/api/generate"
    payload = {
        "model": settings.OSINT_OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "format": "json",
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
    raw = resp.json().get("response", "{}")
    return json.loads(raw)


async def _enrich_event_async(event_id: str) -> dict:
    """Enrich a single event with NLP classification."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from osint_core.config import get_settings
    from osint_core.models import Event

    settings = get_settings()
    engine = create_async_engine(settings.OSINT_DATABASE_URL, pool_class=None)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        event = await db.get(Event, event_id, options=[])
        if event is None:
            return {"event_id": event_id, "status": "not_found"}

        # Skip if already enriched
        if event.nlp_relevance and event.nlp_summary:
            return {"event_id": event_id, "status": "skipped"}

        # Check if plan has enrichment enabled
        plan_content = {}
        if event.plan_version:
            plan_content = event.plan_version.content or {}

        enrichment = plan_content.get("enrichment", {})
        if not enrichment.get("nlp_enabled", False):
            return {"event_id": event_id, "status": "nlp_disabled"}

        mission = enrichment.get("mission", "")
        keywords = plan_content.get("keywords", [])

        prompt = _ENRICH_PROMPT.format(
            title=event.title or "",
            metadata=json.dumps(event.metadata_ or {}, default=str)[:500],
            mission=mission,
            keywords=", ".join(keywords),
        )

        try:
            result = await _call_ollama(prompt)
        except (TimeoutError, httpx.TimeoutException, httpx.HTTPError, json.JSONDecodeError) as e:
            logger.warning("NLP enrichment fallback for %s: %s", event_id, e)
            return {"event_id": event_id, "status": "fallback"}

        if not event.summary and result.get("summary"):
            event.nlp_summary = result["summary"]

        relevance = result.get("relevance", "")
        if relevance in ("relevant", "tangential", "irrelevant"):
            event.nlp_relevance = relevance

        await db.commit()

    await engine.dispose()
    return {"event_id": event_id, "status": "enriched"}


@shared_task(name="osint.nlp_enrich_event", bind=True, max_retries=1)
def nlp_enrich_task(self, event_id: str) -> dict:
    """Celery task wrapper for NLP enrichment."""
    try:
        loop = asyncio.new_event_loop()
        return loop.run_until_complete(_enrich_event_async(event_id))
    except Exception as exc:
        logger.exception("NLP enrichment failed for %s", event_id)
        raise self.retry(exc=exc, countdown=30)
    finally:
        loop.close()
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/jacorbello/repos/osint-core && python -m pytest tests/workers/test_enrich.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/osint_core/workers/enrich.py tests/workers/test_enrich.py
git commit -m "feat(enrich): add NLP enrichment task with Ollama for summary, relevance, entities"
```

---

### Task 8: Rewire Ingest Pipeline — Insert NLP Before Score

**Files:**
- Modify: `src/osint_core/workers/ingest.py`
- Modify: `tests/workers/test_ingest.py`

- [ ] **Step 1: Update task chaining in `_ingest_source_async`**

Replace the downstream task dispatch (currently 3 independent `.delay()` calls) with:

```python
from celery import chain, group
from osint_core.workers.enrich import nlp_enrich_task
from osint_core.workers.score import score_event_task
from osint_core.workers.vectorize import vectorize_event_task
from osint_core.workers.correlate import correlate_event_task

for eid in new_event_ids:
    chain(
        nlp_enrich_task.si(eid),
        group(score_event_task.si(eid), vectorize_event_task.si(eid)),
        correlate_event_task.si(eid),
    ).apply_async()
```

- [ ] **Step 2: Update ingest tests to expect chain instead of delay**

- [ ] **Step 3: Run tests**

Run: `cd /Users/jacorbello/repos/osint-core && python -m pytest tests/workers/test_ingest.py -v`

- [ ] **Step 4: Commit**

```bash
git add src/osint_core/workers/ingest.py tests/workers/test_ingest.py
git commit -m "feat(ingest): rewire pipeline as chain(enrich -> group(score, vectorize) -> correlate)"
```

---

## Chunk 4: Near-Duplicate Detection

### Task 9: SimHash Implementation

**Files:**
- Create: `src/osint_core/services/dedup.py`
- Create: `tests/services/test_dedup.py`

- [ ] **Step 1: Write failing tests**

Create `tests/services/test_dedup.py`:

```python
"""Tests for near-duplicate detection via SimHash."""
import pytest
from osint_core.services.dedup import compute_simhash, simhash_distance, normalize_title


class TestNormalizeTitle:
    def test_lowercase_and_strip(self):
        assert normalize_title("  Hello WORLD  ") == "hello world"

    def test_strip_punctuation(self):
        assert normalize_title("Hello, World! — Test") == "hello world  test"

    def test_empty(self):
        assert normalize_title("") == ""

    def test_none(self):
        assert normalize_title(None) == ""


class TestSimHash:
    def test_identical_titles_same_hash(self):
        h1 = compute_simhash("bombing in downtown austin texas")
        h2 = compute_simhash("bombing in downtown austin texas")
        assert h1 == h2

    def test_similar_titles_close_distance(self):
        h1 = compute_simhash("Snow and wind batter parts of US with threat of storms")
        h2 = compute_simhash("Snow and wind batter parts of US with threat of thunderstorms")
        assert simhash_distance(h1, h2) <= 3

    def test_different_titles_far_distance(self):
        h1 = compute_simhash("bombing in downtown austin texas")
        h2 = compute_simhash("new materials industry conference in jinan china")
        assert simhash_distance(h1, h2) > 3

    def test_empty_string(self):
        h = compute_simhash("")
        assert isinstance(h, int)
```

- [ ] **Step 2: Implement SimHash**

Create `src/osint_core/services/dedup.py`:

```python
"""Near-duplicate detection using SimHash."""
from __future__ import annotations

import hashlib
import re
import string

_STOPWORDS = frozenset(
    "a an the and or but in on at to for of is it this that with from by as".split()
)


def normalize_title(title: str | None) -> str:
    if not title:
        return ""
    text = title.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)
    return text


def _shingle(text: str, n: int = 3) -> list[str]:
    words = [w for w in text.split() if w not in _STOPWORDS]
    if len(words) < n:
        return [" ".join(words)] if words else []
    return [" ".join(words[i : i + n]) for i in range(len(words) - n + 1)]


def compute_simhash(text: str, bits: int = 64) -> int:
    text = normalize_title(text)
    shingles = _shingle(text)
    if not shingles:
        return 0

    v = [0] * bits
    for shingle in shingles:
        h = int(hashlib.md5(shingle.encode()).hexdigest(), 16) % (2**bits)
        for i in range(bits):
            if h & (1 << i):
                v[i] += 1
            else:
                v[i] -= 1

    result = 0
    for i in range(bits):
        if v[i] > 0:
            result |= 1 << i
    return result


def simhash_distance(h1: int, h2: int) -> int:
    return bin(h1 ^ h2).count("1")
```

- [ ] **Step 3: Run tests**

Run: `cd /Users/jacorbello/repos/osint-core && python -m pytest tests/services/test_dedup.py -v`

- [ ] **Step 4: Wire SimHash into ingest pipeline**

In `src/osint_core/workers/ingest.py`, after creating the Event:

```python
from osint_core.services.dedup import compute_simhash, simhash_distance

# Compute and store simhash
event.simhash = compute_simhash(event.title)

# Check for near-duplicates in recent events
if event.simhash:
    recent_stmt = (
        select(Event.id, Event.simhash)
        .where(Event.simhash.isnot(None))
        .where(Event.ingested_at >= datetime.now(timezone.utc) - timedelta(hours=24))
        .where(Event.canonical_event_id.is_(None))
        .limit(500)
    )
    recent = (await db.execute(recent_stmt)).all()
    for existing_id, existing_hash in recent:
        if existing_hash and simhash_distance(event.simhash, existing_hash) <= 3:
            event.canonical_event_id = existing_id
            # Increment corroboration on canonical event
            canonical = await db.get(Event, existing_id)
            if canonical:
                canonical.corroboration_count = (canonical.corroboration_count or 0) + 1
            break
```

- [ ] **Step 5: Run ingest tests**

Run: `cd /Users/jacorbello/repos/osint-core && python -m pytest tests/workers/test_ingest.py tests/services/test_dedup.py -v`

- [ ] **Step 6: Commit**

```bash
git add src/osint_core/services/dedup.py tests/services/test_dedup.py src/osint_core/workers/ingest.py
git commit -m "feat(dedup): add SimHash near-duplicate detection with corroboration"
```

---

## Chunk 5: Alert Routing & Rules Engine

### Task 10: Alert Rules Evaluation Engine

**Files:**
- Create: `src/osint_core/services/alert_rules.py`
- Create: `tests/services/test_alert_rules.py`

- [ ] **Step 1: Write failing tests**

Create `tests/services/test_alert_rules.py`:

```python
"""Tests for alert rule evaluation."""
import pytest
from unittest.mock import MagicMock
from osint_core.services.alert_rules import evaluate_rules, AlertRule


def _make_event(severity="high", source_id="cisa_kev", **kwargs):
    event = MagicMock()
    event.severity = severity
    event.source_id = source_id
    event.source_category = kwargs.get("source_category")
    event.country_code = kwargs.get("country_code")
    event.simhash = kwargs.get("simhash", 0)
    return event


class TestEvaluateRules:
    def test_severity_exact_match(self):
        rules = [AlertRule(
            name="critical-alert",
            condition={"severity": "critical"},
            channels=["gotify"],
            cooldown_minutes=15,
        )]
        event = _make_event(severity="critical")
        matched = evaluate_rules(event, rules)
        assert len(matched) == 1
        assert matched[0].name == "critical-alert"

    def test_severity_gte(self):
        rules = [AlertRule(
            name="high-plus",
            condition={"severity": {"gte": "high"}},
            channels=["gotify"],
            cooldown_minutes=15,
        )]
        event = _make_event(severity="critical")
        matched = evaluate_rules(event, rules)
        assert len(matched) == 1

    def test_no_match(self):
        rules = [AlertRule(
            name="critical-only",
            condition={"severity": "critical"},
            channels=["gotify"],
            cooldown_minutes=15,
        )]
        event = _make_event(severity="low")
        assert evaluate_rules(event, rules) == []

    def test_multiple_conditions_anded(self):
        rules = [AlertRule(
            name="kev-high",
            condition={"severity": {"gte": "medium"}, "source_id": "cisa_kev"},
            channels=["gotify", "email"],
            cooldown_minutes=60,
        )]
        event = _make_event(severity="high", source_id="cisa_kev")
        assert len(evaluate_rules(event, rules)) == 1

        event2 = _make_event(severity="high", source_id="nvd_recent")
        assert evaluate_rules(event2, rules) == []

    def test_multiple_rules_can_match(self):
        rules = [
            AlertRule(name="r1", condition={"severity": "critical"}, channels=["gotify"], cooldown_minutes=15),
            AlertRule(name="r2", condition={"severity": {"gte": "high"}}, channels=["email"], cooldown_minutes=30),
        ]
        event = _make_event(severity="critical")
        assert len(evaluate_rules(event, rules)) == 2
```

- [ ] **Step 2: Implement alert rules engine**

Create `src/osint_core/services/alert_rules.py`:

```python
"""Alert rule evaluation engine."""
from __future__ import annotations

from dataclasses import dataclass, field

_SEVERITY_ORDER = ["info", "low", "medium", "high", "critical"]


@dataclass
class AlertRule:
    name: str
    condition: dict
    channels: list[str]
    cooldown_minutes: int


def _severity_index(s: str) -> int:
    try:
        return _SEVERITY_ORDER.index(s)
    except ValueError:
        return -1


def _match_condition_field(event, field_name: str, expected) -> bool:
    actual = getattr(event, field_name, None)
    if actual is None:
        return False

    if isinstance(expected, dict):
        if "gte" in expected:
            if field_name == "severity":
                return _severity_index(actual) >= _severity_index(expected["gte"])
            return actual >= expected["gte"]
        if "lte" in expected:
            if field_name == "severity":
                return _severity_index(actual) <= _severity_index(expected["lte"])
            return actual <= expected["lte"]
        return False

    return actual == expected


def evaluate_rules(event, rules: list[AlertRule]) -> list[AlertRule]:
    """Return list of rules whose conditions match the event."""
    matched = []
    for rule in rules:
        if all(
            _match_condition_field(event, field, value)
            for field, value in rule.condition.items()
        ):
            matched.append(rule)
    return matched


def parse_rules_from_plan(plan_content: dict) -> list[AlertRule]:
    """Parse alert rules from plan YAML content."""
    alerts = plan_content.get("alerts", {})
    raw_rules = alerts.get("rules", [])

    # Legacy format support
    notifications = plan_content.get("notifications", {})
    legacy_routes = notifications.get("routes", [])

    rules = []
    for r in raw_rules:
        rules.append(AlertRule(
            name=r["name"],
            condition=r.get("condition", {}),
            channels=r.get("channels", ["gotify"]),
            cooldown_minutes=r.get("cooldown_minutes", 30),
        ))

    # Map legacy routes to alert rules
    for route in legacy_routes:
        when = route.get("when", {})
        sev = when.get("severity_gte")
        if sev:
            rules.append(AlertRule(
                name=route.get("name", f"legacy-{sev}"),
                condition={"severity": {"gte": sev}},
                channels=["gotify"],
                cooldown_minutes=route.get("dedupe_window_minutes", 30),
            ))

    return rules
```

- [ ] **Step 3: Run tests**

Run: `cd /Users/jacorbello/repos/osint-core && python -m pytest tests/services/test_alert_rules.py -v`

- [ ] **Step 4: Commit**

```bash
git add src/osint_core/services/alert_rules.py tests/services/test_alert_rules.py
git commit -m "feat(alerts): add rule evaluation engine with legacy notification support"
```

---

### Task 11: Update Notify Worker — Multi-Channel Routing & Cooldown

**Files:**
- Modify: `src/osint_core/workers/notify.py`
- Modify: `tests/workers/test_notify.py`

- [ ] **Step 1: Add email channel support**

Add to `notify.py`:

```python
import smtplib
from email.message import EmailMessage

def _send_email(subject: str, body: str, recipients: list[str]) -> bool:
    settings = get_settings()
    smtp_host = getattr(settings, "OSINT_SMTP_HOST", None)
    if not smtp_host:
        logger.warning("SMTP not configured, skipping email")
        return False
    msg = EmailMessage()
    msg["Subject"] = f"[OSINT Alert] {subject}"
    msg["From"] = getattr(settings, "OSINT_SMTP_FROM", "osint@corbello.io")
    msg["To"] = ", ".join(recipients)
    msg.set_content(body)
    with smtplib.SMTP(smtp_host) as server:
        server.send_message(msg)
    return True


def _send_webhook(url: str, payload: dict) -> bool:
    with httpx.Client(timeout=10) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
    return True
```

- [ ] **Step 2: Update `send_notification` to route to multiple channels**

Update the task to accept a `matched_rules` parameter and route accordingly:

```python
@shared_task(name="osint.send_notification", bind=True, max_retries=3)
def send_notification(self, alert_id: str, matched_rules: list[dict] | None = None) -> dict:
    # ... load alert and event
    # For each matched rule, check cooldown, then send to each channel
    for rule in matched_rules or [{"channels": ["gotify"], "cooldown_minutes": 30}]:
        channels = rule.get("channels", ["gotify"])
        for channel in channels:
            if channel == "gotify":
                _post_to_gotify(title, message, priority)
            elif channel == "email":
                # Load email config from plan alerts.channels.email
                _send_email(title, message, recipients)
            elif channel == "webhook":
                _send_webhook(webhook_url, {"title": title, "message": message})
```

- [ ] **Step 3: Add cooldown check**

```python
import hashlib

def _cooldown_key(rule_name: str, source_id: str, simhash: int) -> str:
    raw = f"{rule_name}:{source_id}:{simhash}"
    return hashlib.sha256(raw.encode()).hexdigest()

# In send_notification, before sending:
# Check alerts table for existing alert with same fingerprint within cooldown window
```

- [ ] **Step 4: Update score worker to pass matched rules to notification**

In `score.py` `_score_event_async`, after severity is set, replace the existing force_alert logic:

```python
from osint_core.services.alert_rules import parse_rules_from_plan, evaluate_rules

rules = parse_rules_from_plan(plan_content)
matched = evaluate_rules(event, rules)
if matched:
    alert_id = await _create_alert(db, event, severity, raw_score)
    send_notification.delay(alert_id, [{"name": r.name, "channels": r.channels, "cooldown_minutes": r.cooldown_minutes} for r in matched])
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/jacorbello/repos/osint-core && python -m pytest tests/workers/test_notify.py tests/workers/test_score.py -v`

- [ ] **Step 6: Commit**

```bash
git add src/osint_core/workers/notify.py src/osint_core/workers/score.py tests/workers/test_notify.py
git commit -m "feat(notify): multi-channel routing with email, webhook, cooldown support"
```

---

## Chunk 6: New Source Connectors (Tier 1)

### Task 12: AlienVault OTX Connector

**Files:**
- Create: `src/osint_core/connectors/otx.py`
- Create: `tests/connectors/test_otx.py`
- Modify: `src/osint_core/connectors/__init__.py`

- [ ] **Step 1: Write failing test**

Create `tests/connectors/test_otx.py`:

```python
"""Tests for AlienVault OTX connector."""
import pytest
import httpx
import respx
from osint_core.connectors.otx import OtxConnector
from osint_core.connectors.base import SourceConfig


@respx.mock
@pytest.mark.asyncio
async def test_fetches_pulses_and_extracts_iocs():
    cfg = SourceConfig(
        id="otx_feed", type="otx_api",
        url="https://otx.alienvault.com/api/v1/pulses/subscribed",
        weight=1.0,
        extra={"api_key": "test-key"},
    )
    respx.get(cfg.url).mock(return_value=httpx.Response(200, json={
        "results": [{
            "id": "pulse-1",
            "name": "Malware Campaign X",
            "description": "New malware targeting enterprise systems",
            "created": "2026-03-16T12:00:00",
            "indicators": [
                {"type": "IPv4", "indicator": "1.2.3.4"},
                {"type": "domain", "indicator": "evil.com"},
                {"type": "CVE", "indicator": "CVE-2026-1234"},
            ],
        }],
    }))
    conn = OtxConnector(cfg)
    items = await conn.fetch()
    assert len(items) == 1
    assert items[0].title == "Malware Campaign X"
    assert len(items[0].indicators) == 3
    assert items[0].indicators[0]["type"] == "IPv4"
```

- [ ] **Step 2: Implement OTX connector**

Create `src/osint_core/connectors/otx.py`:

```python
"""AlienVault OTX pulse feed connector."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import httpx

from .base import BaseConnector, RawItem


class OtxConnector(BaseConnector):
    async def fetch(self) -> list[RawItem]:
        api_key = self.config.extra.get("api_key", "")
        headers = {"X-OTX-API-KEY": api_key}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(self.config.url, headers=headers)
            resp.raise_for_status()
        pulses = resp.json().get("results", [])
        max_items = self.config.extra.get("max_items", 100)
        return [self._parse_pulse(p) for p in pulses[:max_items]]

    def _parse_pulse(self, pulse: dict) -> RawItem:
        created = pulse.get("created", "")
        occurred_at = None
        if created:
            try:
                occurred_at = datetime.fromisoformat(created).replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        indicators = [
            {"type": i["type"], "value": i["indicator"]}
            for i in pulse.get("indicators", [])
        ]
        return RawItem(
            title=pulse.get("name", ""),
            url=f"https://otx.alienvault.com/pulse/{pulse.get('id', '')}",
            raw_data=pulse,
            summary=pulse.get("description", ""),
            occurred_at=occurred_at,
            indicators=indicators,
            source_category="cyber",
        )

    def dedupe_key(self, item: RawItem) -> str:
        pulse_id = item.raw_data.get("id", item.url)
        return f"otx:{hashlib.sha256(pulse_id.encode()).hexdigest()[:16]}"
```

- [ ] **Step 3: Register in `__init__.py`**

Add to `src/osint_core/connectors/__init__.py`:
```python
from .otx import OtxConnector
registry.register("otx_api", OtxConnector)
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/jacorbello/repos/osint-core && python -m pytest tests/connectors/test_otx.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/osint_core/connectors/otx.py tests/connectors/test_otx.py src/osint_core/connectors/__init__.py
git commit -m "feat(connectors): add AlienVault OTX pulse feed connector"
```

---

### Task 13: Abuse.ch Connectors (MalwareBazaar + FeodoTracker)

**Files:**
- Create: `src/osint_core/connectors/abusech.py`
- Create: `tests/connectors/test_abusech.py`
- Modify: `src/osint_core/connectors/__init__.py`

- [ ] **Step 1: Write failing tests**

Create `tests/connectors/test_abusech.py`:

```python
"""Tests for Abuse.ch connectors."""
import pytest
import httpx
import respx
from osint_core.connectors.abusech import MalwareBazaarConnector, FeodoTrackerConnector
from osint_core.connectors.base import SourceConfig


@respx.mock
@pytest.mark.asyncio
async def test_malwarebazaar_parses_samples():
    cfg = SourceConfig(
        id="mb_recent", type="abusech_malwarebazaar",
        url="https://mb-api.abuse.ch/api/v1/",
        weight=1.0, extra={},
    )
    respx.post(cfg.url).mock(return_value=httpx.Response(200, json={
        "query_status": "ok",
        "data": [{
            "sha256_hash": "abc123def456",
            "file_type": "exe",
            "signature": "AgentTesla",
            "first_seen": "2026-03-16 12:00:00",
            "tags": ["stealer"],
        }],
    }))
    conn = MalwareBazaarConnector(cfg)
    items = await conn.fetch()
    assert len(items) == 1
    assert "AgentTesla" in items[0].title
    assert items[0].indicators[0]["type"] == "sha256"


@respx.mock
@pytest.mark.asyncio
async def test_feodotracker_parses_c2_ips():
    cfg = SourceConfig(
        id="feodo_recent", type="abusech_feodotracker",
        url="https://feodotracker.abuse.ch/downloads/ipblocklist_recent.json",
        weight=1.0, extra={},
    )
    respx.get(cfg.url).mock(return_value=httpx.Response(200, json=[
        {
            "ip_address": "1.2.3.4",
            "port": 443,
            "status": "online",
            "malware": "Dridex",
            "first_seen": "2026-03-16",
            "country": "US",
        },
    ]))
    conn = FeodoTrackerConnector(cfg)
    items = await conn.fetch()
    assert len(items) == 1
    assert items[0].indicators[0]["value"] == "1.2.3.4"
    assert items[0].country_code == "USA"
```

- [ ] **Step 2: Implement connectors**

Create `src/osint_core/connectors/abusech.py`:

```python
"""Abuse.ch connectors: MalwareBazaar and FeodoTracker."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import httpx

from .base import BaseConnector, RawItem

_COUNTRY_ISO2_TO_ISO3 = {
    "US": "USA", "GB": "GBR", "CN": "CHN", "RU": "RUS", "DE": "DEU",
    "FR": "FRA", "NL": "NLD", "JP": "JPN", "KR": "KOR", "IN": "IND",
    "BR": "BRA", "CA": "CAN", "AU": "AUS", "IT": "ITA", "ES": "ESP",
}


class MalwareBazaarConnector(BaseConnector):
    async def fetch(self) -> list[RawItem]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                self.config.url,
                data={"query": "get_recent", "selector": "time"},
            )
            resp.raise_for_status()
        samples = resp.json().get("data") or []
        max_items = self.config.extra.get("max_items", 100)
        return [self._parse(s) for s in samples[:max_items]]

    def _parse(self, sample: dict) -> RawItem:
        sig = sample.get("signature") or "Unknown"
        sha = sample.get("sha256_hash", "")
        seen = sample.get("first_seen", "")
        occurred_at = None
        if seen:
            try:
                occurred_at = datetime.strptime(seen, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return RawItem(
            title=f"Malware sample: {sig} ({sample.get('file_type', '')})",
            url=f"https://bazaar.abuse.ch/sample/{sha}/",
            raw_data=sample,
            summary=f"Tags: {', '.join(sample.get('tags') or [])}",
            occurred_at=occurred_at,
            indicators=[{"type": "sha256", "value": sha}],
            source_category="cyber",
        )

    def dedupe_key(self, item: RawItem) -> str:
        sha = item.raw_data.get("sha256_hash", item.url)
        return f"mb:{sha[:16]}"


class FeodoTrackerConnector(BaseConnector):
    async def fetch(self) -> list[RawItem]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(self.config.url)
            resp.raise_for_status()
        entries = resp.json() if isinstance(resp.json(), list) else []
        max_items = self.config.extra.get("max_items", 100)
        return [self._parse(e) for e in entries[:max_items]]

    def _parse(self, entry: dict) -> RawItem:
        ip = entry.get("ip_address", "")
        malware = entry.get("malware", "Unknown")
        seen = entry.get("first_seen", "")
        occurred_at = None
        if seen:
            try:
                occurred_at = datetime.strptime(seen, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        country_iso2 = entry.get("country", "")
        country_code = _COUNTRY_ISO2_TO_ISO3.get(country_iso2, country_iso2)
        return RawItem(
            title=f"C2 server: {ip}:{entry.get('port', '')} ({malware})",
            url=f"https://feodotracker.abuse.ch/browse/host/{ip}/",
            raw_data=entry,
            occurred_at=occurred_at,
            indicators=[{"type": "ip", "value": ip}],
            source_category="cyber",
            country_code=country_code if len(country_code) == 3 else None,
        )

    def dedupe_key(self, item: RawItem) -> str:
        ip = item.raw_data.get("ip_address", item.url)
        return f"feodo:{hashlib.sha256(ip.encode()).hexdigest()[:16]}"
```

- [ ] **Step 3: Register both**

Add to `__init__.py`:
```python
from .abusech import MalwareBazaarConnector, FeodoTrackerConnector
registry.register("abusech_malwarebazaar", MalwareBazaarConnector)
registry.register("abusech_feodotracker", FeodoTrackerConnector)
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/jacorbello/repos/osint-core && python -m pytest tests/connectors/test_abusech.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/osint_core/connectors/abusech.py tests/connectors/test_abusech.py src/osint_core/connectors/__init__.py
git commit -m "feat(connectors): add Abuse.ch MalwareBazaar and FeodoTracker connectors"
```

---

### Task 14: ACLED Connector

**Files:**
- Create: `src/osint_core/connectors/acled.py`
- Create: `tests/connectors/test_acled.py`
- Modify: `src/osint_core/connectors/__init__.py`

- [ ] **Step 1: Write failing test**

Create `tests/connectors/test_acled.py`:

```python
"""Tests for ACLED conflict data connector."""
import pytest
import httpx
import respx
from osint_core.connectors.acled import AcledConnector
from osint_core.connectors.base import SourceConfig


@respx.mock
@pytest.mark.asyncio
async def test_parses_conflict_events():
    cfg = SourceConfig(
        id="acled_global", type="acled_api",
        url="https://api.acleddata.com/acled/read",
        weight=1.0,
        extra={"api_key": "test", "email": "test@test.com"},
    )
    respx.get(cfg.url).mock(return_value=httpx.Response(200, json={
        "status": 200,
        "data": [{
            "event_id_cnty": "USA12345",
            "event_date": "2026-03-16",
            "event_type": "Protests",
            "sub_event_type": "Peaceful protest",
            "actor1": "Protesters",
            "country": "United States",
            "iso3": "USA",
            "latitude": "30.2672",
            "longitude": "-97.7431",
            "fatalities": "0",
            "notes": "Peaceful march in downtown Austin",
        }],
    }))
    conn = AcledConnector(cfg)
    items = await conn.fetch()
    assert len(items) == 1
    assert items[0].country_code == "USA"
    assert items[0].latitude == pytest.approx(30.2672)
    assert items[0].fatalities == 0
```

- [ ] **Step 2: Implement connector**

Create `src/osint_core/connectors/acled.py`:

```python
"""ACLED conflict event data connector."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import httpx

from .base import BaseConnector, RawItem


class AcledConnector(BaseConnector):
    async def fetch(self) -> list[RawItem]:
        params = {
            "key": self.config.extra.get("api_key", ""),
            "email": self.config.extra.get("email", ""),
            "limit": str(self.config.extra.get("max_items", 100)),
        }
        country = self.config.extra.get("country")
        if country:
            params["country"] = country
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(self.config.url, params=params)
            resp.raise_for_status()
        events = resp.json().get("data", [])
        return [self._parse(e) for e in events if e.get("notes")]

    def _parse(self, event: dict) -> RawItem:
        date_str = event.get("event_date", "")
        occurred_at = None
        if date_str:
            try:
                occurred_at = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        lat = event.get("latitude")
        lon = event.get("longitude")
        fatalities_raw = event.get("fatalities", "0")
        return RawItem(
            title=f"{event.get('event_type', '')}: {event.get('notes', '')[:100]}",
            url=f"https://acleddata.com/data-export-tool/?event_id={event.get('event_id_cnty', '')}",
            raw_data=event,
            summary=event.get("notes", ""),
            occurred_at=occurred_at,
            latitude=float(lat) if lat else None,
            longitude=float(lon) if lon else None,
            country_code=event.get("iso3"),
            source_category="geopolitical",
            event_type=event.get("event_type"),
            event_subtype=event.get("sub_event_type"),
            fatalities=int(fatalities_raw) if fatalities_raw else 0,
            actors=[{"name": event.get("actor1", ""), "role": "primary"}] if event.get("actor1") else [],
        )

    def dedupe_key(self, item: RawItem) -> str:
        eid = item.raw_data.get("event_id_cnty", item.url)
        return f"acled:{hashlib.sha256(eid.encode()).hexdigest()[:16]}"
```

- [ ] **Step 3: Register and run tests**

Add `from .acled import AcledConnector` and `registry.register("acled_api", AcledConnector)` to `__init__.py`.

Run: `cd /Users/jacorbello/repos/osint-core && python -m pytest tests/connectors/test_acled.py -v`

- [ ] **Step 4: Commit**

```bash
git add src/osint_core/connectors/acled.py tests/connectors/test_acled.py src/osint_core/connectors/__init__.py
git commit -m "feat(connectors): add ACLED conflict event data connector"
```

---

### Task 15: NWS Alerts Connector

**Files:**
- Create: `src/osint_core/connectors/nws.py`
- Create: `tests/connectors/test_nws.py`
- Modify: `src/osint_core/connectors/__init__.py`

- [ ] **Step 1: Write failing test**

Create `tests/connectors/test_nws.py`:

```python
"""Tests for NWS weather alert connector."""
import pytest
import httpx
import respx
from osint_core.connectors.nws import NwsConnector
from osint_core.connectors.base import SourceConfig


@respx.mock
@pytest.mark.asyncio
async def test_parses_weather_alerts():
    cfg = SourceConfig(
        id="nws_austin", type="nws_alerts",
        url="https://api.weather.gov/alerts/active",
        weight=1.0,
        extra={"zone": "TXC453"},
    )
    respx.get(cfg.url).mock(return_value=httpx.Response(200, json={
        "features": [{
            "id": "urn:oid:2.49.0.1.840.0.abc",
            "properties": {
                "headline": "Tornado Warning for Travis County",
                "description": "A tornado warning has been issued...",
                "severity": "Severe",
                "event": "Tornado Warning",
                "onset": "2026-03-16T14:00:00-05:00",
                "areaDesc": "Travis County, TX",
            },
        }],
    }))
    conn = NwsConnector(cfg)
    items = await conn.fetch()
    assert len(items) == 1
    assert "Tornado Warning" in items[0].title
    assert items[0].severity == "high"  # Severe -> high
```

- [ ] **Step 2: Implement connector**

Create `src/osint_core/connectors/nws.py`:

```python
"""NWS (National Weather Service) alerts connector."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import httpx

from .base import BaseConnector, RawItem

_NWS_SEVERITY_MAP = {
    "Extreme": "critical",
    "Severe": "high",
    "Moderate": "medium",
    "Minor": "low",
    "Unknown": "info",
}


class NwsConnector(BaseConnector):
    async def fetch(self) -> list[RawItem]:
        params = {}
        zone = self.config.extra.get("zone")
        if zone:
            params["zone"] = zone
        headers = {"User-Agent": "(osint-core, admin@corbello.io)", "Accept": "application/geo+json"}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(self.config.url, params=params, headers=headers)
            resp.raise_for_status()
        features = resp.json().get("features", [])
        max_items = self.config.extra.get("max_items", 100)
        return [self._parse(f) for f in features[:max_items]]

    def _parse(self, feature: dict) -> RawItem:
        props = feature.get("properties", {})
        onset = props.get("onset", "")
        occurred_at = None
        if onset:
            try:
                occurred_at = datetime.fromisoformat(onset).astimezone(timezone.utc)
            except ValueError:
                pass
        nws_severity = props.get("severity", "Unknown")
        return RawItem(
            title=props.get("headline", props.get("event", "")),
            url=f"https://alerts.weather.gov/search?id={feature.get('id', '')}",
            raw_data=props,
            summary=props.get("description", "")[:500],
            occurred_at=occurred_at,
            severity=_NWS_SEVERITY_MAP.get(nws_severity, "info"),
            source_category="weather",
            country_code="USA",
        )

    def dedupe_key(self, item: RawItem) -> str:
        alert_id = item.raw_data.get("id", item.url)
        return f"nws:{hashlib.sha256(str(alert_id).encode()).hexdigest()[:16]}"
```

- [ ] **Step 3: Register and run tests**

Add `from .nws import NwsConnector` and `registry.register("nws_alerts", NwsConnector)` to `__init__.py`.

Run: `cd /Users/jacorbello/repos/osint-core && python -m pytest tests/connectors/test_nws.py -v`

- [ ] **Step 4: Commit**

```bash
git add src/osint_core/connectors/nws.py tests/connectors/test_nws.py src/osint_core/connectors/__init__.py
git commit -m "feat(connectors): add NWS weather alert connector with severity mapping"
```

---

### Task 16: Add New Sources to Plan YAMLs

**Files:**
- Modify: `plans/cyber-threat-intel.yaml`
- Modify: `plans/austin-terror-watch.yaml`
- Modify: `plans/humanitarian-intel.yaml`

- [ ] **Step 1: Add new sources to plans**

`cyber-threat-intel.yaml` — add:
```yaml
  - id: otx_pulses
    type: otx_api
    url: https://otx.alienvault.com/api/v1/pulses/subscribed
    params:
      api_key: "${OSINT_OTX_API_KEY}"
      max_items: 50
    schedule: "0 */4 * * *"

  - id: mb_recent
    type: abusech_malwarebazaar
    url: https://mb-api.abuse.ch/api/v1/
    params:
      max_items: 50
    schedule: "30 */4 * * *"

  - id: feodo_recent
    type: abusech_feodotracker
    url: https://feodotracker.abuse.ch/downloads/ipblocklist_recent.json
    params:
      max_items: 50
    schedule: "0 */6 * * *"
```

Add to scoring.source_reputation:
```yaml
    otx_pulses: 0.67
    mb_recent: 0.6
    feodo_recent: 0.6
```

`austin-terror-watch.yaml` — add:
```yaml
  - id: nws_austin
    type: nws_alerts
    url: https://api.weather.gov/alerts/active
    params:
      zone: TXC453
    schedule: "*/15 * * * *"

  - id: acled_us
    type: acled_api
    url: https://api.acleddata.com/acled/read
    params:
      api_key: "${OSINT_ACLED_API_KEY}"
      email: "${OSINT_ACLED_EMAIL}"
      country: "United States"
      max_items: 50
    schedule: "0 */4 * * *"
```

Add to scoring.source_reputation:
```yaml
    nws_austin: 0.67
    acled_us: 0.67
```

`humanitarian-intel.yaml` — add:
```yaml
  - id: acled_global
    type: acled_api
    url: https://api.acleddata.com/acled/read
    params:
      api_key: "${OSINT_ACLED_API_KEY}"
      email: "${OSINT_ACLED_EMAIL}"
      max_items: 100
    schedule: "0 */4 * * *"
```

Add to scoring.source_reputation:
```yaml
    acled_global: 0.67
```

- [ ] **Step 2: Commit**

```bash
git add plans/
git commit -m "feat(plans): add OTX, Abuse.ch, ACLED, NWS sources to plan configs"
```

---

## Chunk 7: Search Validation & Final Integration

### Task 17: Search Validation Tests

**Files:**
- Create: `tests/integration/test_search_validation.py`

- [ ] **Step 1: Write search validation test suite**

```python
"""Search validation tests — verify full-text and semantic search work correctly."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_fulltext_search_returns_relevant(async_client: AsyncClient):
    """Full-text search for 'CVE-2026' should return cyber events."""
    resp = await async_client.get("/api/v1/search", params={"q": "CVE-2026"})
    assert resp.status_code == 200
    items = resp.json().get("items", [])
    # All results should have CVE in title or summary
    for item in items:
        text = f"{item.get('title', '')} {item.get('summary', '')}".lower()
        assert "cve" in text


@pytest.mark.asyncio
async def test_search_filterable_by_plan(async_client: AsyncClient):
    """Search should support plan_id filter."""
    resp = await async_client.get("/api/v1/search", params={"q": "attack", "plan_id": "austin-terror-watch"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_events_sorted_by_score(async_client: AsyncClient):
    """Events sorted by -score should be descending."""
    resp = await async_client.get("/api/v1/events", params={"sort": "-score", "limit": 50})
    assert resp.status_code == 200
    items = resp.json().get("items", [])
    scores = [i["score"] for i in items if i["score"] is not None]
    assert scores == sorted(scores, reverse=True)
```

- [ ] **Step 2: Run against live API or test fixtures**

Run: `cd /Users/jacorbello/repos/osint-core && python -m pytest tests/integration/test_search_validation.py -v --tb=short`

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_search_validation.py
git commit -m "test: add search validation suite for full-text, plan-scoped, and sort ordering"
```

---

### Task 18: Remove Dead Code

**Files:**
- Modify: `src/osint_core/services/scoring.py` (already rewritten in Task 2, verify no orphans)

- [ ] **Step 1: Verify `score_event_v2`, `RELIABILITY_FACTORS`, `ReliabilityProfile`, `CORROBORATION_BONUS` are removed**

These should already be gone from the Task 2 rewrite. Confirm with grep.

Run: `cd /Users/jacorbello/repos/osint-core && grep -rn "score_event_v2\|RELIABILITY_FACTORS\|ReliabilityProfile\|CORROBORATION_BONUS" src/`

Expected: No results (all removed)

- [ ] **Step 2: Remove `weight` from SourceConfig if not already done**

In `src/osint_core/connectors/base.py`, check if `weight` field is still used anywhere. If not, remove it from the dataclass and update any references.

Run: `cd /Users/jacorbello/repos/osint-core && grep -rn "\.weight" src/ tests/`

- [ ] **Step 3: Commit if changes needed**

```bash
git add -u
git commit -m "chore: remove dead scoring code and deprecated weight field"
```

---

### Task 19: Full Integration Test Run

- [ ] **Step 1: Run complete test suite**

Run: `cd /Users/jacorbello/repos/osint-core && python -m pytest tests/ -v --tb=short 2>&1 | tail -50`

Fix any failures.

- [ ] **Step 2: Run linter**

Run: `cd /Users/jacorbello/repos/osint-core && ruff check src/ tests/`

Fix any issues.

- [ ] **Step 3: Final commit if fixes needed**

```bash
git add -u
git commit -m "fix: resolve test and lint issues from platform tuning"
```

---

### Task 20: Rescore Existing Events

- [ ] **Step 1: Trigger rescore via API**

```bash
curl -X POST 'https://osint.corbello.io/api/v1/events/rescore'
```

- [ ] **Step 2: Verify improved scoring**

```bash
curl -s 'https://osint.corbello.io/api/v1/events?sort=-score&limit=20' | python3 -m json.tool
```

Verify:
- Scores span the full 0-1 range
- Severities include info/low/medium/high (not just "low")
- Relevant events score higher than noise
- GDELT noise articles score low (info tier)

- [ ] **Step 3: Commit any config adjustments**
