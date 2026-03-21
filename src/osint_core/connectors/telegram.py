"""Telegram public channel monitor connector."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from osint_core.connectors.base import BaseConnector, RawItem


class TelegramConnector(BaseConnector):
    """Monitors public Telegram channels via the Telegram Bot API.

    Plan YAML params (passed in ``config.extra``):
      - ``channel_username`` – public channel username (without leading ``@``)
      - ``keywords`` – optional list of keyword strings to filter messages
      - ``lookback_hours`` – how far back to fetch (default ``24``)
    """

    # Telegram Bot API base URL
    _API_BASE = "https://api.telegram.org"

    def _resolve_bot_token(self) -> str:
        """Return the bot token from source config or global settings."""
        token: str = self.config.extra.get("bot_token", "")
        if not token:
            from osint_core.config import settings

            token = settings.telegram_bot_token
        if not token:
            raise ValueError(
                "Telegram bot token not configured in source params or "
                "OSINT_TELEGRAM_BOT_TOKEN"
            )
        return token

    async def fetch(self) -> list[RawItem]:
        token = self._resolve_bot_token()
        channel = self.config.extra.get("channel_username", "")
        if not channel:
            raise ValueError("channel_username is required in connector params")

        lookback_hours = int(self.config.extra.get("lookback_hours", 24))
        keywords: list[str] = self.config.extra.get("keywords", [])
        cutoff = datetime.now(tz=UTC) - timedelta(hours=lookback_hours)

        url = f"{self._API_BASE}/bot{token}/getUpdates"
        params: dict[str, Any] = {
            "allowed_updates": '["channel_post"]',
            "timeout": 0,
        }

        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, timeout=30.0)
            resp.raise_for_status()

        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(
                f"Telegram API error: {data.get('description', 'unknown')}"
            )

        results = data.get("result", [])
        items: list[RawItem] = []

        for update in results:
            message = update.get("channel_post") or update.get("message")
            if message is None:
                continue

            # Filter by channel
            chat = message.get("chat", {})
            chat_username = (chat.get("username") or "").lower()
            if chat_username != channel.lower().lstrip("@"):
                continue

            # Parse the message
            item = self._parse_message(message, update)
            if item is None:
                continue

            # Filter by lookback window
            if item.occurred_at is not None and item.occurred_at < cutoff:
                continue

            # Filter by keywords (case-insensitive)
            if keywords and not self._matches_keywords(item, keywords):
                continue

            items.append(item)

        return items

    def _parse_message(
        self, message: dict[str, Any], update: dict[str, Any]
    ) -> RawItem | None:
        """Convert a Telegram message dict into a RawItem."""
        text = message.get("text") or message.get("caption") or ""
        if not text:
            return None

        # Title: first 120 chars of text
        title = text[:120].replace("\n", " ")
        if len(text) > 120:
            title += "..."

        chat = message.get("chat", {})
        chat_username = chat.get("username") or ""
        message_id = message.get("message_id", "")

        # Author
        author = chat.get("title") or chat_username

        # Timestamp
        occurred_at: datetime | None = None
        date_val = message.get("date")
        if date_val is not None:
            occurred_at = datetime.fromtimestamp(date_val, tz=UTC)

        # Media URLs
        media_urls = self._extract_media_urls(message)

        raw_data: dict[str, Any] = {
            "update_id": update.get("update_id"),
            "message_id": message_id,
            "chat_id": chat.get("id"),
            "chat_username": chat_username,
            "author": author,
            "text": text,
            "date": date_val,
            "media_urls": media_urls,
        }

        url = f"https://t.me/{chat_username}/{message_id}" if chat_username else ""

        return RawItem(
            title=title,
            url=url,
            summary=text,
            raw_data=raw_data,
            occurred_at=occurred_at,
        )

    @staticmethod
    def _extract_media_urls(message: dict[str, Any]) -> list[str]:
        """Extract media file references from a Telegram message."""
        urls: list[str] = []

        # Photo — pick the largest resolution
        photos = message.get("photo")
        if photos and isinstance(photos, list):
            urls.append(f"file_id:{photos[-1].get('file_id', '')}")

        # Document, video, audio, voice, animation
        for media_key in ("document", "video", "audio", "voice", "animation"):
            media = message.get(media_key)
            if media and isinstance(media, dict):
                file_id = media.get("file_id", "")
                if file_id:
                    urls.append(f"file_id:{file_id}")

        return urls

    @staticmethod
    def _matches_keywords(item: RawItem, keywords: list[str]) -> bool:
        """Return True if any keyword appears in the item text (case-insensitive)."""
        text_lower = (item.title + " " + item.summary).lower()
        return any(kw.lower() in text_lower for kw in keywords)

    def dedupe_key(self, item: RawItem) -> str:
        message_id = str(item.raw_data.get("message_id", ""))
        chat_id = str(item.raw_data.get("chat_id", ""))
        raw = f"{chat_id}:{message_id}"
        key_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
        return f"telegram:{self.config.id}:{key_hash}"
