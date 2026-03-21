"""Tests for the Telegram channel monitor connector."""

import hashlib
import time

import httpx
import pytest

from osint_core.connectors.base import SourceConfig
from osint_core.connectors.telegram import TelegramConnector

# Timestamp a few minutes ago (within default 24h lookback)
_RECENT_TS = int(time.time()) - 300


def _make_api_response(updates: list) -> dict:
    """Wrap updates in a Telegram Bot API response envelope."""
    return {"ok": True, "result": updates}


def _make_update(
    update_id: int,
    message_id: int,
    text: str,
    chat_username: str = "osint_channel",
    chat_title: str = "OSINT Channel",
    chat_id: int = -1001234567890,
    date: int | None = None,
    photo: list | None = None,
    document: dict | None = None,
) -> dict:
    """Build a single Telegram channel_post update dict."""
    msg: dict = {
        "message_id": message_id,
        "date": date if date is not None else _RECENT_TS,
        "chat": {
            "id": chat_id,
            "username": chat_username,
            "title": chat_title,
            "type": "channel",
        },
        "text": text,
    }
    if photo is not None:
        msg["photo"] = photo
        # When photo is present, text becomes caption
        del msg["text"]
        msg["caption"] = text
    if document is not None:
        msg["document"] = document
    return {"update_id": update_id, "channel_post": msg}


SAMPLE_UPDATES = _make_api_response(
    [
        _make_update(
            update_id=100,
            message_id=1,
            text="New APT campaign targeting financial institutions",
        ),
        _make_update(
            update_id=101,
            message_id=2,
            text="Malware sample hash: abc123def456",
        ),
    ]
)


@pytest.fixture()
def config() -> SourceConfig:
    return SourceConfig(
        id="telegram-osint",
        type="telegram",
        url="https://api.telegram.org",
        weight=0.5,
        extra={
            "bot_token": "123456:ABC-DEF",
            "channel_username": "osint_channel",
        },
    )


@pytest.fixture()
def connector(config: SourceConfig) -> TelegramConnector:
    return TelegramConnector(config)


def _mock_telegram_api(respx_mock, connector: TelegramConnector, response_data: dict):
    """Mock the Telegram getUpdates endpoint."""
    token = connector.config.extra["bot_token"]
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    respx_mock.get(url).mock(
        return_value=httpx.Response(200, json=response_data)
    )


@pytest.mark.asyncio
async def test_fetch_parses_channel_posts(connector: TelegramConnector, respx_mock):
    _mock_telegram_api(respx_mock, connector, SAMPLE_UPDATES)
    items = await connector.fetch()
    assert len(items) == 2


@pytest.mark.asyncio
async def test_fetch_extracts_title(connector: TelegramConnector, respx_mock):
    _mock_telegram_api(respx_mock, connector, SAMPLE_UPDATES)
    items = await connector.fetch()
    assert items[0].title == "New APT campaign targeting financial institutions"
    assert items[1].title == "Malware sample hash: abc123def456"


@pytest.mark.asyncio
async def test_fetch_extracts_summary(connector: TelegramConnector, respx_mock):
    _mock_telegram_api(respx_mock, connector, SAMPLE_UPDATES)
    items = await connector.fetch()
    assert "APT campaign" in items[0].summary


@pytest.mark.asyncio
async def test_fetch_extracts_timestamp(connector: TelegramConnector, respx_mock):
    _mock_telegram_api(respx_mock, connector, SAMPLE_UPDATES)
    items = await connector.fetch()
    assert items[0].occurred_at is not None
    # Verify timestamp matches the fixed _RECENT_TS from test data
    assert items[0].occurred_at.timestamp() == pytest.approx(_RECENT_TS, abs=1)


@pytest.mark.asyncio
async def test_fetch_extracts_author(connector: TelegramConnector, respx_mock):
    _mock_telegram_api(respx_mock, connector, SAMPLE_UPDATES)
    items = await connector.fetch()
    assert items[0].raw_data["author"] == "OSINT Channel"


@pytest.mark.asyncio
async def test_fetch_extracts_media_urls(connector: TelegramConnector, respx_mock):
    updates = _make_api_response(
        [
            _make_update(
                update_id=200,
                message_id=10,
                text="Screenshot of C2 panel",
                photo=[
                    {"file_id": "small_photo", "width": 100, "height": 100},
                    {"file_id": "large_photo", "width": 800, "height": 600},
                ],
            ),
        ]
    )
    _mock_telegram_api(respx_mock, connector, updates)
    items = await connector.fetch()
    assert len(items) == 1
    # Media URLs should be Bot API getFile URLs, not raw file_id references
    media = items[0].raw_data["media_urls"]
    assert len(media) == 1
    assert "getFile?file_id=large_photo" in media[0]


@pytest.mark.asyncio
async def test_dedupe_key_by_message_id(connector: TelegramConnector, respx_mock):
    _mock_telegram_api(respx_mock, connector, SAMPLE_UPDATES)
    items = await connector.fetch()

    chat_id = str(items[0].raw_data["chat_id"])
    message_id = str(items[0].raw_data["message_id"])
    raw = f"{chat_id}:{message_id}"
    expected_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]

    assert connector.dedupe_key(items[0]) == f"telegram:telegram-osint:{expected_hash}"


@pytest.mark.asyncio
async def test_dedupe_keys_differ_across_messages(connector: TelegramConnector, respx_mock):
    _mock_telegram_api(respx_mock, connector, SAMPLE_UPDATES)
    items = await connector.fetch()
    assert connector.dedupe_key(items[0]) != connector.dedupe_key(items[1])


@pytest.mark.asyncio
async def test_keyword_filtering(connector: TelegramConnector, respx_mock):
    """Only messages matching keywords should be returned."""
    config = SourceConfig(
        id="telegram-filtered",
        type="telegram",
        url="https://api.telegram.org",
        weight=0.5,
        extra={
            "bot_token": "123456:ABC-DEF",
            "channel_username": "osint_channel",
            "keywords": ["malware"],
        },
    )
    filtered_connector = TelegramConnector(config)
    _mock_telegram_api(respx_mock, filtered_connector, SAMPLE_UPDATES)
    items = await filtered_connector.fetch()
    assert len(items) == 1
    assert "Malware" in items[0].title


@pytest.mark.asyncio
async def test_filters_other_channels(connector: TelegramConnector, respx_mock):
    """Messages from other channels should be excluded."""
    updates = _make_api_response(
        [
            _make_update(
                update_id=300,
                message_id=50,
                text="Unrelated message",
                chat_username="other_channel",
            ),
        ]
    )
    _mock_telegram_api(respx_mock, connector, updates)
    items = await connector.fetch()
    assert len(items) == 0


@pytest.mark.asyncio
async def test_empty_response(connector: TelegramConnector, respx_mock):
    _mock_telegram_api(respx_mock, connector, _make_api_response([]))
    items = await connector.fetch()
    assert items == []


@pytest.mark.asyncio
async def test_api_error_raises(connector: TelegramConnector, respx_mock):
    error_response = {"ok": False, "description": "Unauthorized"}
    _mock_telegram_api(respx_mock, connector, error_response)
    with pytest.raises(RuntimeError, match="Telegram API error"):
        await connector.fetch()


@pytest.mark.asyncio
async def test_missing_bot_token_raises():
    config = SourceConfig(
        id="no-token",
        type="telegram",
        url="https://api.telegram.org",
        weight=0.5,
        extra={"channel_username": "osint_channel"},
    )
    connector = TelegramConnector(config)
    with pytest.raises(ValueError, match="bot token"):
        await connector.fetch()


@pytest.mark.asyncio
async def test_missing_channel_username_raises():
    config = SourceConfig(
        id="no-channel",
        type="telegram",
        url="https://api.telegram.org",
        weight=0.5,
        extra={"bot_token": "123456:ABC-DEF"},
    )
    connector = TelegramConnector(config)
    with pytest.raises(ValueError, match="channel_username"):
        await connector.fetch()
