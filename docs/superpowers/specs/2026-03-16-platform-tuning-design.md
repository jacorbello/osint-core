# OSINT Platform Tuning — Design Spec

**Date:** 2026-03-16
**Status:** Approved
**Scope:** Scoring overhaul, connector hardening, NLP enrichment, alert routing, new sources, dedup, search validation

---

## Problem Statement

The OSINT platform is live but producing low-quality results:

1. **Scoring is broken** — the multiplicative formula (`base_reputation x recency_decay x ioc_multiplier x topic_relevance`) produces scores in a narrow band (0.0–0.87). Severity thresholds at 1/3/7 are unreachable — every event is "low."
2. **GDELT floods noise** — no geographic or topic pre-filtering. Chinese industry news, Korean entertainment, and wrestling results are top-scoring events in the Austin terror watch plan.
3. **Keyword matching is shallow** — most GDELT events have empty summaries. Title-only matching fails on non-English content.
4. **Alerting can't fire** — depends on severity thresholds that are never reached.
5. **Alert routing is basic** — single Gotify channel, no per-severity routing or custom rules.
6. **Source coverage gaps** — missing free, high-value feeds.
7. **Near-duplicates slip through** — exact SHA-256 dedup misses same story from multiple outlets.
8. **Search unvalidated** — full-text and semantic search exist but haven't been stress-tested.

---

## 1. Scoring Overhaul

### Current Formula (Broken)

```
score = base_reputation x recency_decay x ioc_multiplier x topic_relevance
```

All factors are <= 1.5, so the product is always < 1.0. Severity thresholds at 1/3/7 are unreachable.

### New Formula

```
relevance_score = keyword_relevance x geographic_relevance x source_trust
    -> normalized to 0.0-1.0

recency_factor = max(0.1, 0.5^(hours_old / half_life))
    -> floored at 0.1 so critical old items don't vanish

final_score = relevance_score x recency_factor
    -> 0.0-1.0

severity = max(formula_severity, signal_promoted_severity)
```

### Formula-Based Severity Thresholds

| Range | Severity |
|-------|----------|
| 0.0–0.2 | info |
| 0.2–0.5 | low |
| 0.5–0.75 | medium |
| 0.75–1.0 | high |

### Signal-Based Severity Promotions

Plans define promotion rules that can override formula-based severity. Promotions can only elevate, never downgrade.

```yaml
scoring:
  severity_promotions:
    - condition: {field: "indicators.cvss", op: "gte", value: 9.0}
      promote_to: critical
    - condition: {field: "source_id", op: "eq", value: "cisa_kev"}
      promote_to: high
```

Condition operators: `eq`, `neq`, `gte`, `lte`, `gt`, `lt`, `contains`, `in`.

Fields available: `severity`, `source_id`, `source_category`, `indicators.cvss`, `indicators.type`, `keywords_matched` (count), `geographic_match` (bool), `country_code`, `event_type`, `fatalities`.

### Scoring Factor Details

**Keyword relevance:**
- Weighted score: `matched_keywords / total_plan_keywords`
- Title matches weighted 2x vs summary matches
- NLP relevance classification (Section 3) overrides when available:
  - `relevant` -> 1.0
  - `tangential` -> 0.4
  - `irrelevant` -> 0.05

**Geographic relevance:**
- Plans define target geographies (country codes, lat/lon + radius)
- Exact match -> 1.0
- Partial match (same country, different region) -> 0.5
- No geo data available -> 0.7 (benefit of doubt)
- Confirmed irrelevant geography -> 0.2

**Source trust:**
- Per-source reputation defined in plan YAML, range 0.0-1.0
- Unknown sources default to 0.5

### Corroboration Bonus

When near-duplicate detection (Section 6) identifies multiple sources reporting the same event, the canonical event gets a corroboration boost:
- 1.2x per additional corroborating source, capped at 1.5x
- Applied after the base relevance_score calculation

---

## 2. GDELT Filtering & Connector Improvements

### GDELT Query Tightening

- Add `sourcelang` parameter — plans specify preferred languages as a soft filter (non-preferred languages still ingested but inform scoring)
- Add geographic bounding via `sourcelocation` or geo keyword terms in query
- Configurable `lookback_hours` per source (default 4h for frequent polls, replacing current 25h)
- Use `mode: ArtList` for deduplicated article lists

### Connector-Level Post-Fetch Filtering

- **Near-duplicate detection:** Normalize titles (lowercase, strip punctuation, remove stopwords), compute similarity. Skip if similarity > configurable threshold (default 0.85) to an already-ingested event in same batch.
- **Minimum content threshold:** Skip articles with empty title AND empty summary.
- **Domain dedup:** Cap articles per domain per fetch (configurable `max_per_domain`, default 5).
- **Max items cap:** All connectors get a `max_items` limit per fetch (default 100).

### Plan-Level Source Config

```yaml
sources:
  - id: gdelt_austin_terror
    type: gdelt_api
    extra:
      query: "terrorism OR shooter OR attack OR bombing"
      geo_terms: "Austin OR Texas OR Travis County"
      lookback_hours: 4
      preferred_languages: ["English", "Spanish"]
      max_per_domain: 5
      near_dedup_threshold: 0.85
```

### Other Connector Improvements

- RSS connectors: `If-Modified-Since` / ETag support to skip unchanged feeds
- All connectors: structured error reporting surfaced via jobs API

---

## 3. NLP Enrichment Pipeline

### Pipeline Position

```
Fetch -> Ingest -> NLP Enrich -> Score -> Vectorize -> Correlate
```

New async Celery task `nlp_enrich_task` inserted between ingest and score.

### What It Does (Per Event)

1. **Summary generation** — for events with empty summaries, generate a 1-2 sentence English summary from title + metadata. Provides English text for keyword matching on non-English articles.
2. **Relevance classification** — given plan's mission and keywords, classify as `relevant`, `tangential`, or `irrelevant`. Directly feeds keyword_relevance in scoring.
3. **Entity extraction** — extract people, organizations, locations, threat indicators. Feeds geographic relevance scoring, near-dedup, and entity linking.

### Implementation

- Uses existing Ollama/LLaMA 3.1:8b stack
- Single structured prompt per event (summary + classification + entities in one call)
- Batch processing: 10-20 events per batch for throughput
- Cache/skip: if event already has summary and entities, skip NLP pass
- Timeout/fallback: if Ollama unavailable or > 10s per event, fall back to keyword-only scoring. System degrades gracefully.

### Plan YAML

```yaml
enrichment:
  nlp_enabled: true
  mission: "Monitor terrorism, extremism, and mass violence threats in the Austin, Texas metropolitan area"
  classify_relevance: true
  extract_entities: true
  generate_summaries: true
```

Each plan defines its own `mission` statement for relevance classification context.

---

## 4. Alert Routing & Rules Engine

### Alert Configuration (Plan YAML)

```yaml
alerts:
  channels:
    gotify:
      url: "${OSINT_GOTIFY_URL}"
      token: "${OSINT_GOTIFY_TOKEN}"
      priority_map:
        critical: 10
        high: 8
        medium: 5
    email:
      smtp_host: "${OSINT_SMTP_HOST}"
      recipients: ["jacorbello@gmail.com"]
    webhook:
      url: "${OSINT_WEBHOOK_URL}"

  rules:
    - name: critical-immediate
      condition:
        severity: critical
      channels: [gotify, email, webhook]
      cooldown_minutes: 15

    - name: high-push
      condition:
        severity: high
      channels: [gotify]
      cooldown_minutes: 30

    - name: kev-exploit
      condition:
        source_id: cisa_kev
        severity:
          gte: medium
      channels: [gotify, email]
      cooldown_minutes: 60

    - name: local-threat
      condition:
        keywords_matched:
          gte: 2
        geographic_match: true
      channels: [gotify, email]
      cooldown_minutes: 15

  digest:
    schedule: "0 8 * * *"
    channels: [email]
    min_severity: low
    max_events: 50
```

### How It Works

- After scoring, the notify worker evaluates each alert rule against the event
- Multiple rules can match — each fires independently
- **Cooldown:** if a rule already fired for a similar event (same source + similar title hash) within cooldown window, suppress
- **Digest:** aggregates lower-severity events into scheduled summary
- Channel configs support env var interpolation for secrets
- Alert history stored in `alerts` table for audit
- Conditions within a rule are AND-ed

### Alert Rule Condition Fields

`severity`, `source_id`, `source_category`, `keywords_matched` (count), `geographic_match` (bool), `indicator_type`, `country_code`

---

## 5. New Source Connectors (Tier 1)

### AlienVault OTX (`otx_api`)

- **Endpoint:** `https://otx.alienvault.com/api/v1/pulses/subscribed`
- **Auth:** Free API key required
- **Returns:** Pulses with IOCs (IPs, domains, URLs, file hashes, CVEs)
- **Maps to:** cyber-threat-intel plan
- **Indicators extracted:** IP, domain, URL, hash, CVE
- **Source reputation:** 1.0

### Abuse.ch Feeds (`abusech_api`)

- **MalwareBazaar:** `https://mb-api.abuse.ch/api/v1/` — recent malware samples
- **FeodoTracker:** `https://feodotracker.abuse.ch/downloads/ipblocklist_recent.json` — C2 IPs
- **Auth:** None required
- **Maps to:** cyber-threat-intel plan
- **Indicators:** File hashes (SHA256), C2 IPs, malware families
- **Source reputation:** 0.9

### ACLED (`acled_api`)

- **Endpoint:** `https://api.acleddata.com/acled/read`
- **Auth:** Free API key required
- **Returns:** Conflict events with geocoding, fatality counts, actor info, event types (battles, protests, violence against civilians, explosions)
- **Maps to:** humanitarian-intel, austin-terror-watch
- **Geo-coded natively** — feeds directly into geographic relevance scoring
- **Source reputation:** 1.0

### NWS Alerts (`nws_alerts`)

- **Endpoint:** `https://api.weather.gov/alerts/active`
- **Auth:** None required
- **Filter by zone:** Austin = `TXC453`
- **Returns:** Severe weather, flood, tornado warnings with built-in severity
- **Maps to:** austin-terror-watch (situational awareness), humanitarian-intel
- **Source reputation:** 1.0
- **Severity mapping:** Extreme -> critical, Severe -> high, Moderate -> medium, Minor -> low

---

## 6. Near-Duplicate Detection

### Current State

Exact SHA-256 hash of `{plan_id, source_id, raw_item_data}`. Misses same story from different outlets or same CVE from NVD + KEV + OSV.

### Title Similarity (SimHash)

- Normalize title: lowercase, strip punctuation, remove stopwords
- Compute SimHash
- Events with SimHash distance <= 3 within a 24-hour window are dedup candidates
- First ingested event is canonical; subsequent near-duplicates are linked as corroboration

### Indicator-Based Dedup

- If two events share the same CVE ID or IOC value, link them as related
- First event is canonical, subsequent events add corroboration
- Corroboration boost: 1.2x per additional source, capped at 1.5x

---

## 7. Search Validation

Not a redesign — a verification pass:

- **Full-text search (tsvector):** Verify enriched events with generated summaries are indexed. Test targeted queries against each plan's domain.
- **Semantic search (Qdrant):** Verify vectorized events return semantically similar results (e.g., "supply chain compromise" surfaces related attacks).
- **Plan-scoped search:** Verify searches can be filtered by plan to avoid cross-domain noise.
- **Fix** anything found broken. Leave working systems alone.

---

## Deferred Work (GitHub Tickets)

The following items from Approach 3 are tracked as separate GitHub issues:

1. **Scoring feedback loop** — analyst UI for flagging false positives/negatives to tune scoring weights over time
2. **Tier 2 sources** — PhishTank, MITRE ATT&CK updates, DHS/ICS-CERT advisories, Austin PD data portal
3. **Tier 3 sources** — social media (Twitter/X, Reddit, Telegram), commercial feeds (VirusTotal, Recorded Future), FEMA/IPAWS

---

## Architecture Notes

- All changes follow existing patterns: Celery tasks, SQLAlchemy models, FastAPI routes, plan YAML config
- NLP enrichment is the only new infrastructure dependency and it uses the existing Ollama stack
- Scoring changes are backward-compatible — old events can be rescored via existing `/rescore` endpoint
- New connectors follow the `BaseConnector` / `ConnectorRegistry` pattern
- Alert rules are evaluated in the existing notify worker, extended with routing logic
