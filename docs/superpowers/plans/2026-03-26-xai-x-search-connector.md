# xAI X Search Connector — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a native `xai_x_search` connector that searches X/Twitter via xAI's Grok API, producing one RawItem per cited tweet.

**Architecture:** Single new connector file following existing patterns (Reddit, ACLED). Reads plan config for search queries and mission context, builds a Grok prompt, calls the xAI Responses API with the `x_search` tool, parses individual tweets from the response (JSON primary, annotation fallback), and returns RawItems for the standard ingest pipeline.

**Tech Stack:** Python 3.12, httpx, structlog, pytest + respx

**Spec:** `docs/superpowers/specs/2026-03-26-xai-x-search-connector-design.md`

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `src/osint_core/connectors/xai_x_search.py` | Create | New connector — prompt building, API call, response parsing, dedup |
| `src/osint_core/connectors/__init__.py` | Modify (lines 1-65) | Import and register `xai_x_search` |
| `plans/austin-terror-threat.yaml` | Modify | Add `x_austin_threats` source + source_profile + scoring |
| `tests/connectors/test_xai_x_search.py` | Create | Full test suite for the connector |

---

### Task 1: Create Connector with Tests — Core Fetch and JSON Parsing

**Files:**
- Create: `src/osint_core/connectors/xai_x_search.py`
- Create: `tests/connectors/test_xai_x_search.py`

- [ ] **Step 1: Write the test file with core tests**

Create `tests/connectors/test_xai_x_search.py`:

```python
"""Tests for the xAI X Search connector."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import httpx
import pytest

from osint_core.connectors.base import SourceConfig
from osint_core.connectors.xai_x_search import XaiXSearchConnector

# ---------------------------------------------------------------------------
# Sample responses
# ---------------------------------------------------------------------------

SAMPLE_JSON_RESPONSE = {
    "id": "resp_001",
    "output": [
        {
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": json.dumps([
                        {
                            "tweet_url": "https://x.com/AustinPD/status/111111",
                            "author": "@AustinPD",
                            "text": "APD responding to reports of shots fired near downtown.",
                            "timestamp": "2026-03-26T10:30:00Z",
                            "category": "Active Shooter",
                        },
                        {
                            "tweet_url": "https://x.com/KVUE/status/222222",
                            "author": "@KVUE",
                            "text": "Breaking: police activity reported near Congress Ave.",
                            "timestamp": "2026-03-26T10:45:00Z",
                            "category": "Law Enforcement",
                        },
                    ]),
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url": "https://x.com/AustinPD/status/111111",
                        },
                        {
                            "type": "url_citation",
                            "url": "https://x.com/KVUE/status/222222",
                        },
                    ],
                }
            ],
        }
    ],
    "usage": {"server_side_tool_usage_details": {"x_search_calls": 4}},
}

SAMPLE_ANNOTATION_ONLY_RESPONSE = {
    "id": "resp_002",
    "output": [
        {
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": "I found some relevant posts about threats in Austin.",
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url": "https://x.com/AlertAustin/status/333333",
                        },
                        {
                            "type": "url_citation",
                            "url": "https://x.com/TravisCoSO/status/444444",
                        },
                        {
                            "type": "url_citation",
                            "url": "https://not-twitter.com/other/page",
                        },
                    ],
                }
            ],
        }
    ],
}

SAMPLE_EMPTY_RESPONSE = {
    "id": "resp_003",
    "output": [
        {
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": "No relevant tweets found for the given searches.",
                    "annotations": [],
                }
            ],
        }
    ],
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def config() -> SourceConfig:
    return SourceConfig(
        id="x_test",
        type="xai_x_search",
        url="",
        weight=0.4,
        extra={
            "api_key": "xai-test-key-123",
            "searches": [
                "(shooting OR gunfire) Austin lang:en",
                "reports of active shooter in Austin Texas",
            ],
            "mission": "Monitor threats in Austin, TX",
            "geo_terms": "Austin OR Travis County",
            "lookback_hours": 24,
            "max_results": 50,
        },
    )


@pytest.fixture()
def connector(config: SourceConfig) -> XaiXSearchConnector:
    return XaiXSearchConnector(config)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_parses_json_response(
    connector: XaiXSearchConnector, respx_mock,
):
    """JSON array in Grok's text output is parsed into RawItems."""
    respx_mock.post("https://api.x.ai/v1/responses").mock(
        return_value=httpx.Response(200, json=SAMPLE_JSON_RESPONSE),
    )
    items = await connector.fetch()

    assert len(items) == 2
    assert items[0].title == "@AustinPD: APD responding to reports of shots fired near downtown."
    assert items[0].url == "https://x.com/AustinPD/status/111111"
    assert items[0].source_category == "social_media"
    assert items[0].raw_data["author"] == "@AustinPD"
    assert items[0].occurred_at == datetime(2026, 3, 26, 10, 30, tzinfo=UTC)
    assert items[1].raw_data["category"] == "Law Enforcement"


@pytest.mark.asyncio
async def test_fetch_fallback_to_annotations(
    connector: XaiXSearchConnector, respx_mock,
):
    """When JSON parsing fails, tweets extracted from url_citation annotations."""
    respx_mock.post("https://api.x.ai/v1/responses").mock(
        return_value=httpx.Response(200, json=SAMPLE_ANNOTATION_ONLY_RESPONSE),
    )
    items = await connector.fetch()

    # Should extract 2 x.com URLs, skip the non-twitter one
    assert len(items) == 2
    assert items[0].url == "https://x.com/AlertAustin/status/333333"
    assert items[0].raw_data["author"] == "@AlertAustin"
    assert items[1].raw_data["author"] == "@TravisCoSO"


@pytest.mark.asyncio
async def test_fetch_sends_date_params(
    connector: XaiXSearchConnector, respx_mock,
):
    """from_date and to_date computed from lookback_hours and sent in tool config."""
    route = respx_mock.post("https://api.x.ai/v1/responses").mock(
        return_value=httpx.Response(200, json=SAMPLE_EMPTY_RESPONSE),
    )
    await connector.fetch()

    body = json.loads(route.calls[0].request.content)
    tool = body["tools"][0]
    assert tool["type"] == "x_search"
    assert "from_date" in tool
    assert "to_date" in tool
    # Dates should be YYYY-MM-DD format
    assert len(tool["from_date"]) == 10
    assert len(tool["to_date"]) == 10


@pytest.mark.asyncio
async def test_fetch_sends_tool_params(respx_mock):
    """excluded_x_handles, enable_image_understanding passed to tool object."""
    cfg = SourceConfig(
        id="x_test",
        type="xai_x_search",
        url="",
        weight=0.4,
        extra={
            "api_key": "xai-test-key-123",
            "searches": ["test query"],
            "excluded_x_handles": ["BotAccount", "SpamBot"],
            "enable_image_understanding": True,
        },
    )
    connector = XaiXSearchConnector(cfg)

    route = respx_mock.post("https://api.x.ai/v1/responses").mock(
        return_value=httpx.Response(200, json=SAMPLE_EMPTY_RESPONSE),
    )
    await connector.fetch()

    body = json.loads(route.calls[0].request.content)
    tool = body["tools"][0]
    assert tool["excluded_x_handles"] == ["BotAccount", "SpamBot"]
    assert tool["enable_image_understanding"] is True


@pytest.mark.asyncio
async def test_connector_keys_not_in_body(
    connector: XaiXSearchConnector, respx_mock,
):
    """Connector-only keys are not leaked as top-level API params or tool params."""
    route = respx_mock.post("https://api.x.ai/v1/responses").mock(
        return_value=httpx.Response(200, json=SAMPLE_EMPTY_RESPONSE),
    )
    await connector.fetch()

    body = json.loads(route.calls[0].request.content)
    # These must NOT appear as top-level request body keys
    for key in ("searches", "mission", "geo_terms", "lookback_hours", "max_results"):
        assert key not in body, f"{key} leaked as top-level API param"
    # These must NOT appear as tool-level keys
    tool = body["tools"][0]
    for key in ("searches", "mission", "geo_terms", "lookback_hours", "max_results", "api_key"):
        assert key not in tool, f"{key} leaked as tool param"


@pytest.mark.asyncio
async def test_fetch_sends_auth_header(
    connector: XaiXSearchConnector, respx_mock,
):
    """API key sent as Bearer token in Authorization header."""
    route = respx_mock.post("https://api.x.ai/v1/responses").mock(
        return_value=httpx.Response(200, json=SAMPLE_EMPTY_RESPONSE),
    )
    await connector.fetch()

    auth = route.calls[0].request.headers.get("authorization")
    assert auth == "Bearer xai-test-key-123"


def test_dedupe_key_uses_status_id(connector: XaiXSearchConnector):
    """Dedupe key extracts tweet status ID from URL."""
    from osint_core.connectors.base import RawItem

    item = RawItem(
        title="test",
        url="https://x.com/AustinPD/status/111111",
        raw_data={"tweet_url": "https://x.com/AustinPD/status/111111"},
    )
    assert connector.dedupe_key(item) == "xai:111111"


def test_dedupe_key_fallback_to_hash(connector: XaiXSearchConnector):
    """Dedupe falls back to URL hash when no status ID found."""
    from osint_core.connectors.base import RawItem

    item = RawItem(
        title="test",
        url="https://x.com/some/other/path",
        raw_data={"tweet_url": "https://x.com/some/other/path"},
    )
    key = connector.dedupe_key(item)
    assert key.startswith("xai:")
    assert len(key) > 10  # hash, not empty


@pytest.mark.asyncio
async def test_fetch_raises_on_missing_api_key(respx_mock):
    """ValueError raised when api_key is missing."""
    cfg = SourceConfig(
        id="x_test", type="xai_x_search", url="", weight=0.4,
        extra={"searches": ["test"]},
    )
    connector = XaiXSearchConnector(cfg)
    with pytest.raises(ValueError, match="api_key"):
        await connector.fetch()


@pytest.mark.asyncio
async def test_fetch_raises_on_missing_searches(respx_mock):
    """ValueError raised when searches list is missing or empty."""
    cfg = SourceConfig(
        id="x_test", type="xai_x_search", url="", weight=0.4,
        extra={"api_key": "xai-test"},
    )
    connector = XaiXSearchConnector(cfg)
    with pytest.raises(ValueError, match="searches"):
        await connector.fetch()


@pytest.mark.asyncio
async def test_fetch_empty_results(
    connector: XaiXSearchConnector, respx_mock,
):
    """Empty response returns empty list."""
    respx_mock.post("https://api.x.ai/v1/responses").mock(
        return_value=httpx.Response(200, json=SAMPLE_EMPTY_RESPONSE),
    )
    items = await connector.fetch()
    assert items == []


@pytest.mark.asyncio
async def test_max_results_caps_output(respx_mock):
    """max_results limits the number of RawItems returned."""
    tweets = [
        {
            "tweet_url": f"https://x.com/user/status/{i}",
            "author": f"@user{i}",
            "text": f"Tweet {i}",
            "timestamp": "2026-03-26T10:00:00Z",
            "category": "Test",
        }
        for i in range(10)
    ]
    response = {
        "id": "resp_big",
        "output": [{
            "type": "message",
            "role": "assistant",
            "content": [{
                "type": "output_text",
                "text": json.dumps(tweets),
                "annotations": [],
            }],
        }],
    }
    cfg = SourceConfig(
        id="x_test", type="xai_x_search", url="", weight=0.4,
        extra={
            "api_key": "xai-test",
            "searches": ["test"],
            "max_results": 5,
        },
    )
    connector = XaiXSearchConnector(cfg)
    respx_mock.post("https://api.x.ai/v1/responses").mock(
        return_value=httpx.Response(200, json=response),
    )
    items = await connector.fetch()
    assert len(items) == 5


@pytest.mark.asyncio
async def test_fetch_retries_on_429(
    connector: XaiXSearchConnector, respx_mock,
):
    """429 is retried with backoff, then succeeds."""
    route = respx_mock.post("https://api.x.ai/v1/responses").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "1"}),
            httpx.Response(200, json=SAMPLE_JSON_RESPONSE),
        ],
    )
    items = await connector.fetch()
    assert len(items) == 2
    assert route.call_count == 2  # confirm retry occurred


@pytest.mark.asyncio
async def test_fetch_429_exhaustion_returns_empty(
    connector: XaiXSearchConnector, respx_mock,
):
    """All 3 retry attempts return 429 — graceful degradation to empty list."""
    route = respx_mock.post("https://api.x.ai/v1/responses").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "1"}),
    )
    items = await connector.fetch()
    assert items == []
    assert route.call_count == 3
```

- [ ] **Step 2: Run tests to verify they fail (module not found)**

Run: `python3.12 -m pytest tests/connectors/test_xai_x_search.py -v 2>&1 | tail -5`

Expected: FAIL with `ModuleNotFoundError: No module named 'osint_core.connectors.xai_x_search'`

- [ ] **Step 3: Write the connector implementation**

Create `src/osint_core/connectors/xai_x_search.py`:

```python
"""xAI X Search connector — searches X/Twitter via Grok's x_search tool."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import structlog

from .base import BaseConnector, RawItem

logger = structlog.get_logger()

_API_URL = "https://api.x.ai/v1/responses"
_DEFAULT_MODEL = "grok-4.20-reasoning"
_TWEET_URL_RE = re.compile(r"x\.com/(\w+)/status/(\d+)")

# Keys consumed by the connector, NOT passed to the xAI API.
_CONNECTOR_KEYS = frozenset({
    "api_key", "model", "lookback_hours", "max_results",
    "searches", "geo_terms", "mission",
    "allowed_x_handles", "excluded_x_handles",
    "enable_image_understanding", "enable_video_understanding",
})


class XaiXSearchConnector(BaseConnector):
    """Search X/Twitter via xAI's Grok API with the x_search tool.

    Config ``extra`` params:
        api_key: str             — xAI API key (required, typically ${OSINT_XAI_API_KEY})
        searches: list[str]      — keyword and semantic search queries (required)
        mission: str             — context for Grok about what to look for
        geo_terms: str           — geographic focus area
        model: str               — Grok model (default grok-4.20-reasoning)
        lookback_hours: int      — search window in hours (default 24)
        max_results: int         — cap on returned items (default 50)
        allowed_x_handles: list  — only search these handles (max 10)
        excluded_x_handles: list — exclude these handles (max 10)
        enable_image_understanding: bool — analyze images in posts
        enable_video_understanding: bool — analyze videos in posts
    """

    async def fetch(self) -> list[RawItem]:
        api_key = self.config.extra.get("api_key", "")
        if not api_key:
            raise ValueError("xai_x_search requires api_key in params")

        searches = self.config.extra.get("searches", [])
        if not searches:
            raise ValueError("xai_x_search requires non-empty searches list")

        model = self.config.extra.get("model", _DEFAULT_MODEL)
        max_results = int(self.config.extra.get("max_results", 50))
        lookback_hours = int(self.config.extra.get("lookback_hours", 24))

        prompt = self._build_prompt(searches, max_results)
        tool = self._build_tool(lookback_hours)
        body = {
            "model": model,
            "input": [{"role": "user", "content": prompt}],
            "tools": [tool],
        }

        async with httpx.AsyncClient(timeout=180) as client:
            resp = await self._request_with_retries(client, api_key, body)

        if resp is None:
            return []

        data = resp.json()
        items = self._parse_json_response(data)
        if not items:
            items = self._parse_annotation_fallback(data)

        return items[:max_results]

    def _build_prompt(self, searches: list[str], max_results: int) -> str:
        mission = self.config.extra.get(
            "mission", "Search X/Twitter for relevant signals.",
        )
        geo_terms = self.config.extra.get("geo_terms", "")

        search_lines = "\n".join(
            f"{i + 1}. {q}" for i, q in enumerate(searches)
        )

        parts = [
            "You are an OSINT analyst searching X/Twitter.",
            "",
            "## MISSION",
            mission,
        ]

        if geo_terms:
            parts += ["", "## FOCUS AREA", geo_terms]

        parts += [
            "",
            "## SEARCHES TO EXECUTE",
            "Execute ALL of the following searches:",
            search_lines,
            "",
            "## OUTPUT FORMAT",
            "Return a JSON array. Each item must have:",
            "- tweet_url: full URL (https://x.com/user/status/id)",
            "- author: @username",
            "- text: tweet text (first 500 chars)",
            "- timestamp: ISO 8601 when posted (YYYY-MM-DDTHH:MM:SSZ)",
            "- category: short label for the type of signal",
            "",
            f"Return at most {max_results} tweets. "
            "Return ONLY the JSON array, no other text. "
            "Deduplicate — if the same tweet matches multiple searches, "
            "include it only once.",
        ]

        return "\n".join(parts)

    def _build_tool(self, lookback_hours: int) -> dict[str, Any]:
        now = datetime.now(UTC)
        from_date = (now - timedelta(hours=lookback_hours)).strftime("%Y-%m-%d")
        to_date = now.strftime("%Y-%m-%d")

        tool: dict[str, Any] = {
            "type": "x_search",
            "from_date": from_date,
            "to_date": to_date,
        }

        # Pass through optional tool-level params
        for key in (
            "allowed_x_handles", "excluded_x_handles",
            "enable_image_understanding", "enable_video_understanding",
        ):
            val = self.config.extra.get(key)
            if val is not None:
                tool[key] = val

        return tool

    async def _request_with_retries(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        body: dict[str, Any],
    ) -> httpx.Response | None:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        for attempt in range(3):
            resp = await client.post(_API_URL, json=body, headers=headers)

            if resp.status_code == 429:
                try:
                    retry_after = min(
                        int(resp.headers.get("Retry-After", "10")), 60,
                    )
                except (ValueError, TypeError):
                    retry_after = 10
                logger.warning(
                    "xai_rate_limited",
                    retry_after=retry_after,
                    attempt=attempt + 1,
                )
                if attempt < 2:
                    await asyncio.sleep(retry_after)
                continue

            if resp.status_code in (401, 403):
                logger.error(
                    "xai_auth_error",
                    status=resp.status_code,
                    hint="check OSINT_XAI_API_KEY",
                )
                raise RuntimeError(
                    f"xAI authentication failed (HTTP {resp.status_code})"
                )

            if resp.status_code >= 500:
                logger.warning(
                    "xai_server_error",
                    status=resp.status_code,
                    attempt=attempt + 1,
                )
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
                continue

            resp.raise_for_status()
            return resp

        logger.error("xai_max_retries_exceeded", attempts=3)
        return None

    def _parse_json_response(self, data: dict[str, Any]) -> list[RawItem]:
        text = self._extract_text(data)
        if not text:
            return []

        tweets: list[dict[str, Any]] = []

        # Try bare JSON array
        try:
            json_match = re.search(r"\[\s*\{[\s\S]*?\}\s*\]", text)
            if json_match:
                tweets = json.loads(json_match.group())
            else:
                # Try code block
                code_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
                if code_match:
                    tweets = json.loads(code_match.group(1).strip())
                else:
                    tweets = json.loads(text)
        except json.JSONDecodeError:
            # Try truncated array recovery
            tweets = self._recover_truncated_json(text)
            if tweets:
                logger.warning(
                    "xai_truncated_json_recovered", count=len(tweets),
                )

        if not tweets:
            return []

        items: list[RawItem] = []
        for tweet in tweets:
            item = self._tweet_to_raw_item(tweet)
            if item is not None:
                items.append(item)

        return items

    def _parse_annotation_fallback(
        self, data: dict[str, Any],
    ) -> list[RawItem]:
        logger.warning("xai_json_parse_failed_using_annotations")
        annotations = self._extract_annotations(data)
        text_context = self._extract_text(data) or ""

        items: list[RawItem] = []
        seen_ids: set[str] = set()

        for ann in annotations:
            if ann.get("type") != "url_citation":
                continue
            url = ann.get("url", "")
            match = _TWEET_URL_RE.search(url)
            if not match:
                continue

            author = match.group(1)
            status_id = match.group(2)
            if status_id in seen_ids:
                continue
            seen_ids.add(status_id)

            items.append(
                RawItem(
                    title=f"@{author}: (extracted from citation)",
                    url=url,
                    summary=text_context[:500],
                    raw_data={
                        "tweet_url": url,
                        "author": f"@{author}",
                        "text": "",
                        "timestamp": "",
                        "category": "unknown",
                    },
                    source_category="social_media",
                )
            )

        return items

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        for item in data.get("output", []):
            if item.get("type") == "message":
                for block in item.get("content", []):
                    if block.get("type") in ("output_text", "text"):
                        return block.get("text", "")
        return ""

    @staticmethod
    def _extract_annotations(data: dict[str, Any]) -> list[dict[str, Any]]:
        annotations: list[dict[str, Any]] = []
        for item in data.get("output", []):
            if item.get("type") == "message":
                for block in item.get("content", []):
                    annotations.extend(block.get("annotations", []))
        return annotations

    @staticmethod
    def _recover_truncated_json(text: str) -> list[dict[str, Any]]:
        """Attempt to recover complete objects from a truncated JSON array."""
        # Find the last complete object boundary: "},"  or "}\n]"
        last_complete = text.rfind("},")
        if last_complete == -1:
            last_complete = text.rfind("}")
        if last_complete == -1:
            return []

        candidate = text[: last_complete + 1] + "]"
        # Find the opening bracket
        start = candidate.find("[")
        if start == -1:
            return []

        try:
            return json.loads(candidate[start:])
        except json.JSONDecodeError:
            return []

    @staticmethod
    def _tweet_to_raw_item(
        tweet: dict[str, Any],
    ) -> RawItem | None:
        tweet_url = tweet.get("tweet_url", "")
        if not tweet_url:
            return None

        author = tweet.get("author", "")
        text = tweet.get("text", "")
        timestamp_str = tweet.get("timestamp", "")
        category = tweet.get("category", "")

        occurred_at = None
        if timestamp_str:
            for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
                try:
                    occurred_at = datetime.strptime(
                        timestamp_str, fmt,
                    ).replace(tzinfo=UTC)
                    break
                except (ValueError, TypeError):
                    continue

        return RawItem(
            title=f"{author}: {text[:100]}" if author else text[:100],
            url=tweet_url,
            summary=text[:500],
            raw_data={
                "tweet_url": tweet_url,
                "author": author,
                "text": text,
                "timestamp": timestamp_str,
                "category": category,
            },
            occurred_at=occurred_at,
            source_category="social_media",
        )

    def dedupe_key(self, item: RawItem) -> str:
        tweet_url = item.raw_data.get("tweet_url", item.url)
        match = re.search(r"/status/(\d+)", tweet_url)
        if match:
            return f"xai:{match.group(1)}"
        return f"xai:{hashlib.sha256(tweet_url.encode()).hexdigest()[:16]}"
```

- [ ] **Step 4: Run tests**

Run: `python3.12 -m pytest tests/connectors/test_xai_x_search.py -v`

Expected: ALL pass.

- [ ] **Step 5: Run linter**

Run: `python3.12 -m ruff check src/osint_core/connectors/xai_x_search.py tests/connectors/test_xai_x_search.py`

Expected: No errors. Fix any line-length or import issues.

- [ ] **Step 6: Commit**

```bash
git add src/osint_core/connectors/xai_x_search.py tests/connectors/test_xai_x_search.py
git commit -m "feat: add xAI X Search connector for Twitter/X via Grok API"
```

---

### Task 2: Register Connector

**Files:**
- Modify: `src/osint_core/connectors/__init__.py`

- [ ] **Step 1: Add import and registration**

Edit `src/osint_core/connectors/__init__.py`. Add import after the `urlhaus` import (line 20):

```python
from osint_core.connectors.xai_x_search import XaiXSearchConnector
```

Add to `__all__` list (after `"UrlhausConnector"`):

```python
    "XaiXSearchConnector",
```

Add registration at end of file (after line 64):

```python
registry.register("xai_x_search", XaiXSearchConnector)
```

- [ ] **Step 2: Verify import works**

Run: `python3.12 -c "from osint_core.connectors import registry; assert registry.has('xai_x_search'); print('OK')"`

Expected: `OK`

- [ ] **Step 3: Run all connector tests to verify no regressions**

Run: `python3.12 -m pytest tests/connectors/ -v --tb=short 2>&1 | tail -20`

Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add src/osint_core/connectors/__init__.py
git commit -m "feat: register xai_x_search connector in registry"
```

---

### Task 3: Update Austin Terror Threat Plan

**Files:**
- Modify: `plans/austin-terror-threat.yaml`

- [ ] **Step 1: Add source_profile entry**

Edit `plans/austin-terror-threat.yaml`. Add after `reddit_austin` source_profile (after line 77):

```yaml
  x_austin_threats:
    reliability: D
    credibility: 4
    corroboration_required: true
    license: "api"
```

- [ ] **Step 2: Add source entry**

Add after the `reddit_austin` source (after line 154):

```yaml
  - id: x_austin_threats
    type: xai_x_search
    schedule_cron: "0 */2 * * *"
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
```

- [ ] **Step 3: Add scoring entry**

Add `x_austin_threats: 0.4` to the `scoring.source_reputation` section (after `reddit_austin: 0.3`).

- [ ] **Step 4: Validate YAML**

Run: `python3.12 -c "import yaml; yaml.safe_load(open('plans/austin-terror-threat.yaml')); print('YAML valid')"`

Expected: `YAML valid`

- [ ] **Step 5: Commit**

```bash
git add plans/austin-terror-threat.yaml
git commit -m "feat: add xAI X Search source to austin-terror-threat plan"
```

---

### Task 4: Run Full Test Suite and Lint

- [ ] **Step 1: Run full test suite**

Run: `python3.12 -m pytest tests/ -v --tb=short 2>&1 | tail -30`

Expected: All pass (except pre-existing `sentence_transformers` errors).

- [ ] **Step 2: Run linter on all changed files**

Run: `python3.12 -m ruff check src/osint_core/connectors/xai_x_search.py src/osint_core/connectors/__init__.py tests/connectors/test_xai_x_search.py`

Expected: No errors.

- [ ] **Step 3: Fix any issues and commit**

If lint or test failures: fix, re-run, commit the fix.

---

## Infrastructure Note (Out of Repo)

After merge and deploy:
1. Add `OSINT_XAI_API_KEY` to the worker environment in `cortech-infra` (same pattern as `OSINT_ACLED_EMAIL`). The value should be stored in Infisical as `XAI_API_KEY` and mapped to env var `OSINT_XAI_API_KEY`.
2. Sync plans from disk via `POST /api/v1/plans:sync-from-disk` to pick up the updated `austin-terror-threat.yaml`.
3. Trigger a manual ingest to verify: `POST /api/v1/jobs {"kind": "ingest", "input": {"source_id": "x_austin_threats", "plan_id": "austin-terror-threat"}}`.
