"""Reddit connector — fetches posts from public subreddits via JSON API."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from .base import BaseConnector, RawItem

logger = structlog.get_logger()

_USER_AGENT = "osint-core/1.0 (reddit connector)"


class RedditConnector(BaseConnector):
    """Fetch posts from one or more public subreddits using Reddit's JSON API.

    Config ``extra`` params:
        subreddits: list[str]  — subreddit names (without ``r/`` prefix)
        sort: str              — ``hot``, ``new``, or ``top`` (default ``hot``)
        limit: int             — max posts per subreddit (default 25, max 100)
        keyword_filter: list[str] — if set, only include posts matching any keyword
    """

    async def fetch(self) -> list[RawItem]:
        subreddits: list[str] = self.config.extra.get("subreddits", [])
        sort = self.config.extra.get("sort", "hot")
        limit = min(self.config.extra.get("limit", 25), 100)
        keyword_filter: list[str] = self.config.extra.get("keyword_filter", [])

        if not subreddits:
            logger.warning("reddit_no_subreddits_configured")
            return []

        all_items: list[RawItem] = []
        async with httpx.AsyncClient(
            timeout=30,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            for subreddit in subreddits:
                items = await self._fetch_subreddit(client, subreddit, sort, limit)
                all_items.extend(items)

        if keyword_filter:
            keywords_lower = [kw.lower() for kw in keyword_filter]
            all_items = [
                item
                for item in all_items
                if self._matches_keywords(item, keywords_lower)
            ]

        return all_items

    async def _fetch_subreddit(
        self,
        client: httpx.AsyncClient,
        subreddit: str,
        sort: str,
        limit: int,
    ) -> list[RawItem]:
        url = f"https://www.reddit.com/r/{subreddit}/{sort}.json"
        params = {"limit": str(limit), "raw_json": "1"}

        for attempt in range(3):
            resp = await client.get(url, params=params)
            if resp.status_code == 429:
                try:
                    retry_after = min(
                        int(resp.headers.get("Retry-After", "10")), 60
                    )
                except (ValueError, TypeError):
                    retry_after = 10
                logger.warning(
                    "reddit_rate_limited",
                    subreddit=subreddit,
                    retry_after=retry_after,
                    attempt=attempt + 1,
                )
                if attempt < 2:
                    await asyncio.sleep(retry_after)
                continue
            resp.raise_for_status()
            break
        else:
            logger.error(
                "reddit_max_retries_exceeded",
                subreddit=subreddit,
                attempts=3,
            )
            return []

        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError):
            logger.warning(
                "reddit_non_json_response",
                subreddit=subreddit,
                status=resp.status_code,
                body_preview=resp.text[:200],
            )
            return []

        children = data.get("data", {}).get("children", [])
        return [
            self._parse_post(child.get("data", {}))
            for child in children
            if child.get("data", {}).get("id")
        ]

    def _parse_post(self, post: dict[str, Any]) -> RawItem:
        created_utc = post.get("created_utc")
        occurred_at = None
        if created_utc is not None:
            occurred_at = datetime.fromtimestamp(float(created_utc), tz=UTC)

        # Use selftext for text posts, otherwise the link URL
        post_url = post.get("url", "")
        permalink = post.get("permalink", "")
        full_permalink = (
            f"https://www.reddit.com{permalink}" if permalink else post_url
        )

        return RawItem(
            title=post.get("title", ""),
            url=full_permalink,
            summary=post.get("selftext", "")[:500],
            raw_data={
                "reddit_id": post.get("id", ""),
                "subreddit": post.get("subreddit", ""),
                "author": post.get("author", ""),
                "score": post.get("score", 0),
                "selftext": post.get("selftext", ""),
                "link_url": post_url,
                "created_utc": created_utc,
                "num_comments": post.get("num_comments", 0),
            },
            occurred_at=occurred_at,
            source_category="social_media",
        )

    @staticmethod
    def _matches_keywords(item: RawItem, keywords_lower: list[str]) -> bool:
        text = f"{item.title} {item.summary}".lower()
        return any(kw in text for kw in keywords_lower)

    def dedupe_key(self, item: RawItem) -> str:
        reddit_id = item.raw_data.get("reddit_id", "")
        return f"reddit:{reddit_id}"
