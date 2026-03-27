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
        body: dict[str, Any] = {
            "model": model,
            "input": [{"role": "user", "content": prompt}],
            "tools": [tool],
        }

        async with httpx.AsyncClient(timeout=180) as client:
            resp = await self._request_with_retries(client, api_key, body)

        if resp is None:
            return []

        data = resp.json()
        # Primary: extract tweets from annotations (Grok's native
        # citation behavior with x_search). Fallback: try JSON parsing
        # in case the model returned structured data.
        items = self._parse_annotations(data)
        if not items:
            items = self._parse_json_response(data)
        else:
            # Try to enrich annotation items with structured metadata
            self._enrich_from_json(data, items)

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
            f"Report the top {max_results} most relevant tweets you find. "
            "For EACH tweet, write a short paragraph that includes:",
            "- The @username of the author",
            "- What the tweet says (quote or paraphrase the key content)",
            "- Why it is relevant to the mission",
            "",
            "Write in plain text. Include the tweet URL inline so it "
            "appears as a citation. Do NOT return JSON.",
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

        try:
            parsed = json.loads(text)
            # Structured output returns {"tweets": [...]}
            if isinstance(parsed, dict) and "tweets" in parsed:
                tweets = parsed["tweets"]
            elif isinstance(parsed, list):
                tweets = parsed
        except json.JSONDecodeError:
            # Fallback: regex extraction for unstructured responses
            try:
                json_match = re.search(r"\[\s*\{[\s\S]*?\}\s*\]", text)
                if json_match:
                    tweets = json.loads(json_match.group())
            except json.JSONDecodeError:
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

    def _parse_annotations(
        self, data: dict[str, Any],
    ) -> list[RawItem]:
        logger.info("xai_extracting_from_annotations")
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

            # x.com/i/status/... is a redirect URL — author unknown
            display_author = f"@{author}" if author != "i" else "(unknown)"

            # Extract context around this citation from the response text
            snippet = self._extract_citation_context(
                text_context, url, status_id,
            )

            items.append(
                RawItem(
                    title=f"{display_author}: {snippet[:100]}"
                    if snippet
                    else f"{display_author}: (tweet via x_search)",
                    url=url,
                    summary=snippet[:500] if snippet else text_context[:500],
                    raw_data={
                        "tweet_url": url,
                        "author": display_author,
                        "text": snippet if snippet else text_context[:500],
                        "timestamp": "",
                        "category": "x_search",
                    },
                    source_category="social_media",
                )
            )

        return items

    def _enrich_from_json(
        self, data: dict[str, Any], items: list[RawItem],
    ) -> None:
        """Enrich annotation-extracted items with structured JSON metadata."""
        text = self._extract_text(data)
        if not text:
            return

        tweets: list[dict[str, Any]] = []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and "tweets" in parsed:
                tweets = parsed["tweets"]
            elif isinstance(parsed, list):
                tweets = parsed
        except json.JSONDecodeError:
            return

        if not tweets:
            return

        # Index tweets by status ID for fast lookup
        tweet_by_id: dict[str, dict[str, Any]] = {}
        for tweet in tweets:
            url = tweet.get("tweet_url", "")
            match = re.search(r"/status/(\d+)", url)
            if match:
                tweet_by_id[match.group(1)] = tweet

        # Enrich items
        for item in items:
            match = re.search(r"/status/(\d+)", item.url)
            if not match:
                continue
            tweet: dict[str, Any] | None = tweet_by_id.get(match.group(1))
            if not tweet:
                continue

            # Merge fields that are richer in the JSON response
            if tweet.get("author") and item.raw_data.get("author") in ("(unknown)", ""):
                item.raw_data["author"] = tweet["author"]
                # Update title too
                snippet = item.raw_data.get("text", "")[:100]
                item.title = (
                    f"{tweet['author']}: {snippet}"
                    if snippet
                    else f"{tweet['author']}: (tweet via x_search)"
                )

            if tweet.get("text") and not item.raw_data.get("text"):
                item.raw_data["text"] = tweet["text"]
                item.summary = tweet["text"][:500]

            if tweet.get("timestamp") and not item.raw_data.get("timestamp"):
                item.raw_data["timestamp"] = tweet["timestamp"]
                # Parse occurred_at
                for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
                    try:
                        parsed_dt = datetime.strptime(tweet["timestamp"], fmt)
                        item.occurred_at = (
                            parsed_dt if parsed_dt.tzinfo else parsed_dt.replace(tzinfo=UTC)
                        )
                        break
                    except (ValueError, TypeError):
                        continue

            if tweet.get("category") and item.raw_data.get("category") == "x_search":
                item.raw_data["category"] = tweet["category"]

    @staticmethod
    def _extract_citation_context(
        text: str, url: str, status_id: str,
    ) -> str:
        """Extract text around a citation URL or status ID in the response."""
        # Try to find the URL or status ID in the text and grab surrounding context
        for needle in (url, status_id):
            idx = text.find(needle)
            if idx != -1:
                start = max(0, text.rfind("\n", 0, idx) + 1)
                end = text.find("\n", idx)
                if end == -1:
                    end = min(len(text), idx + 300)
                return text[start:end].strip()
        # Fallback: no context found
        return ""

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        for item in data.get("output", []):
            if item.get("type") == "message":
                for block in item.get("content", []):
                    if block.get("type") in ("output_text", "text"):
                        return str(block.get("text", ""))
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
            result: list[dict[str, Any]] = json.loads(candidate[start:])
            return result
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
                    parsed = datetime.strptime(timestamp_str, fmt)
                    occurred_at = parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
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
