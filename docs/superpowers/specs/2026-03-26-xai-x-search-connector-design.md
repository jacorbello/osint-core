# xAI X Search Connector — Design Spec

**Date:** 2026-03-26
**Status:** Approved
**Scope:** New `xai_x_search` connector that searches X/Twitter via xAI's Grok API with the `x_search` tool, producing one RawItem per cited tweet.

---

## Problem Statement

The OSINT platform lacks real-time social media coverage from X/Twitter. Twitter is one of the fastest sources for threat signals — active shooter reports, suspicious activity, protest escalation — and fills a gap that RSS feeds and Reddit can't cover. The xAI `/v1/responses` API with the `x_search` tool provides both keyword and semantic search across X with date windowing, making it ideal as a connector data source.

---

## Architecture

A native `xai_x_search` connector following the same pattern as existing connectors (Reddit, GDELT, ACLED). The connector:

1. Reads plan config for search queries, geo context, mission, and tool parameters
2. Builds a structured prompt telling Grok to search X and return results as a JSON array
3. Calls the xAI Responses API with the `x_search` tool
4. Parses individual tweets from the response (JSON primary, annotation fallback)
5. Returns one `RawItem` per tweet for the standard ingest pipeline

No new dependencies — uses `httpx` (already in use) and `structlog` (already in use).

---

## Connector Implementation

### New file: `src/osint_core/connectors/xai_x_search.py`

**Registration:** Register as `xai_x_search` in `src/osint_core/connectors/__init__.py`.

### Plan Config Shape

```yaml
- id: x_austin_threats
  type: xai_x_search
  params:
    api_key: "${OSINT_XAI_API_KEY}"
    model: "grok-4.20-reasoning"
    lookback_hours: 24
    max_results: 50
    enable_image_understanding: true
    excluded_x_handles: ["AutoNewsBot", "WeatherAlerts"]
    searches:
      - "(shooting OR shooter OR gunfire) (Austin OR \"Travis County\") lang:en"
      - "(bomb OR explosion OR suspicious package) Austin lang:en"
      - "reports of active shooter or gunfire in Austin Texas area"
      - "suspicious activity or bomb threat near Austin Texas"
    geo_terms: "Austin OR Travis County OR Central Texas"
    mission: "Monitor terrorism, extremism, and mass violence threats in Austin, TX"
  schedule_cron: "*/30 * * * *"
```

All fields under `params` are optional except `api_key` and `searches`. Defaults:
- `model`: `"grok-4.20-reasoning"`
- `lookback_hours`: `24`
- `max_results`: `50`
- `enable_image_understanding`: `false`

### Connector-Only Keys

Same pattern as NVD connector. These keys are consumed by the connector and NOT passed to the xAI API:

```python
_CONNECTOR_KEYS = frozenset({
    "api_key", "model", "lookback_hours", "max_results",
    "searches", "geo_terms", "mission",
    "allowed_x_handles", "excluded_x_handles",
    "enable_image_understanding", "enable_video_understanding",
})
```

### Prompt Construction

The connector builds a prompt from plan config fields. The prompt instructs Grok to execute the searches and return structured JSON.

```
You are an OSINT analyst searching X/Twitter.

## MISSION
{mission or "Search X/Twitter for relevant signals."}

## FOCUS AREA
{geo_terms, if provided}

## SEARCHES TO EXECUTE
Execute ALL of the following searches:
{numbered list of searches from config}

## OUTPUT FORMAT
Return a JSON array. Each item must have:
- tweet_url: full URL (https://x.com/user/status/id)
- author: @username
- text: tweet text (first 500 chars)
- timestamp: ISO 8601 when posted (YYYY-MM-DDTHH:MM:SSZ)
- category: short label for the type of signal

Return at most {max_results} tweets. Return ONLY the JSON array, no other text. Deduplicate — if the same tweet matches multiple searches, include it only once.
```

### API Call

```python
POST https://api.x.ai/v1/responses
Authorization: Bearer {api_key}
Content-Type: application/json

{
    "model": "grok-4.20-reasoning",
    "input": [{"role": "user", "content": prompt}],
    "tools": [{
        "type": "x_search",
        "from_date": "2026-03-25",
        "to_date": "2026-03-26",
        "excluded_x_handles": ["AutoNewsBot"],
        "enable_image_understanding": true
    }]
}
```

- `from_date` / `to_date`: computed from `lookback_hours`, formatted as `YYYY-MM-DD` (date only, per xAI docs). **Note:** Date-only granularity means `lookback_hours: 24` effectively means "today and yesterday" regardless of time of day. This is an xAI API limitation.
- Tool-level params (`allowed_x_handles`, `excluded_x_handles`, `enable_image_understanding`, `enable_video_understanding`) are passed directly from plan config to the tool object.
- Timeout: 180 seconds (Grok needs time to execute multiple searches).
- Retry: 429 with exponential backoff (same pattern as Reddit connector), max 3 attempts.

### Response Parsing

**Two-stage parsing (primary + fallback):**

**Primary — JSON extraction from Grok's text output:**

The response has `output[].content[].text` containing Grok's response. Parse the JSON array using:
1. Regex match for `[{...}]` (bare JSON array)
2. Code block extraction (` ```json ... ``` `)
3. `json.loads` on full text

Each parsed object maps to a tweet with `tweet_url`, `author`, `text`, `timestamp`, `category`.

**Fallback — annotation extraction:**

If JSON parsing fails, extract tweet URLs from `output[].content[].annotations[]` where `type == "url_citation"` and URL matches `x.com/*/status/*`. Parse the author from the URL pattern. Use annotation context as the summary.

If JSON parsing fails due to truncation (Grok hit token limit), attempt to parse up to the last complete object in the array before falling back to annotations. Log a warning when falling back to annotation extraction.

### RawItem Mapping

```python
RawItem(
    title=f"@{author}: {text[:100]}",
    url=tweet_url,
    summary=text[:500],
    raw_data={
        "tweet_url": tweet_url,
        "author": author,
        "text": text,
        "timestamp": timestamp,
        "category": category,
    },
    occurred_at=parsed_timestamp,  # from ISO 8601 string
    source_category="social_media",
)
```

### Deduplication

```python
def dedupe_key(self, item: RawItem) -> str:
    # Extract tweet status ID from URL: https://x.com/user/status/123456
    tweet_url = item.raw_data.get("tweet_url", item.url)
    match = re.search(r"/status/(\d+)", tweet_url)
    if match:
        return f"xai:{match.group(1)}"
    # Fallback: hash the URL
    return f"xai:{hashlib.sha256(tweet_url.encode()).hexdigest()[:16]}"
```

Tweet status ID is globally unique on X, so the same tweet found across different plans, searches, or runs deduplicates naturally (with plan_id in the fingerprint as usual).

### Error Handling

- Missing `api_key`: raise `ValueError` (not retried, same as ACLED)
- Missing `searches`: raise `ValueError`
- HTTP 429: retry with exponential backoff, respecting `Retry-After` header
- HTTP 401/403: log error with key hint, raise (not retried)
- HTTP 5xx: retry with backoff
- Empty response / no tweets found: return empty list, log info
- JSON parse failure + no annotations: return empty list, log warning

---

## Plan Integration

### Austin Terror Threat Plan

Add a new source to `plans/austin-terror-threat.yaml`:

```yaml
  - id: x_austin_threats
    type: xai_x_search
    params:
      api_key: "${OSINT_XAI_API_KEY}"
      model: "grok-4.20-reasoning"
      lookback_hours: 24
      max_results: 50
      enable_image_understanding: true
      searches:
        - "(shooting OR shooter OR gunfire) (Austin OR \"Travis County\") lang:en"
        - "(bomb OR explosion OR suspicious package) Austin lang:en"
        - "(terrorism OR terrorist OR extremist) Texas lang:en"
        - "reports of active shooter or gunfire in Austin Texas area"
        - "suspicious activity or bomb threat near Austin Texas"
        - "mass casualty event or hostage situation in Central Texas"
      geo_terms: "Austin OR Travis County OR Central Texas"
      mission: "Monitor terrorism, extremism, and mass violence threats in Austin, TX"
    schedule_cron: "0 */2 * * *"
```

Schedule: every 2 hours (not every 30 min like RSS — xAI API calls are more expensive and Twitter signals don't need sub-hour latency).

### Source Profile & Scoring

Add to the plan's `source_profiles`:

```yaml
x_austin_threats:
  reliability: D
  credibility: 4
  corroboration_required: true
  license: "api"
```

Add to the plan's `scoring.source_reputation`:

```yaml
x_austin_threats: 0.4
```

Low initial reputation and D reliability (social media is noisy, corroboration required). Matches the pattern used for `reddit_austin`. The NLP enrichment + relevance scoring will promote genuinely relevant tweets.

---

## Credential Management

- xAI API key stored as `OSINT_XAI_API_KEY` in Infisical
- Referenced in plan config as `${OSINT_XAI_API_KEY}` — resolved at ingest time by `_resolve_env_vars()` in `ingest.py` (existing mechanism)
- Added to worker deployment env vars in `cortech-infra` (same pattern as ACLED credentials)

---

## Tests

### Unit Tests: `tests/connectors/test_xai_x_search.py`

- **test_fetch_parses_json_response** — Mock xAI API returning a JSON array of tweets. Verify correct number of RawItems with expected fields.
- **test_fetch_fallback_to_annotations** — Mock response with unparseable text but valid `url_citation` annotations. Verify fallback extracts tweets from annotations.
- **test_fetch_sends_date_params** — Verify `from_date`/`to_date` computed from `lookback_hours` and sent in tool config.
- **test_fetch_sends_tool_params** — Verify `excluded_x_handles`, `enable_image_understanding` passed to tool object from plan config.
- **test_connector_keys_not_in_body** — Verify `searches`, `mission`, `geo_terms`, etc. are not leaked to the API.
- **test_dedupe_key_uses_status_id** — Verify dedupe extracts tweet status ID from URL.
- **test_fetch_retries_on_429** — Mock 429 then 200. Verify retry with backoff.
- **test_fetch_raises_on_missing_api_key** — Verify ValueError for empty api_key.
- **test_fetch_raises_on_missing_searches** — Verify ValueError for empty searches list.
- **test_fetch_empty_results** — Mock response with no tweets. Verify empty list returned.
- **test_max_results_caps_output** — Mock response with 100 tweets, `max_results=50`. Verify only 50 returned.

---

## Files Changed

| File | Change |
|------|--------|
| `src/osint_core/connectors/xai_x_search.py` | Create — new connector |
| `src/osint_core/connectors/__init__.py` | Modify — register `xai_x_search` type |
| `plans/austin-terror-threat.yaml` | Modify — add `x_austin_threats` source |
| `tests/connectors/test_xai_x_search.py` | Create — connector tests |

## Out of Scope

- Streaming responses (not needed for batch ingest)
- Video understanding (can be added later via plan config)
- n8n integration or webhook proxy
- Web search tool (`web_search` is a separate xAI tool, not needed here)
- Modifying the xAI API key in the n8n workflow (separate operational concern)
