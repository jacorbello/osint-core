"""Tests for CourtListener citation verification client."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from osint_core.services.courtlistener import (
    CourtListenerClient,
    _parse_response,
    _RateLimiter,
)


class TestParseResponse:
    def test_parses_verified_citation(self):
        data = [
            {
                "case_name": "Tinker v. Des Moines",
                "citation": "393 U.S. 503",
                "absolute_url": "/opinion/12345/tinker-v-des-moines/",
            }
        ]
        result = _parse_response(data)
        assert len(result) == 1
        assert result[0].case_name == "Tinker v. Des Moines"
        assert result[0].citation == "393 U.S. 503"
        assert result[0].verified is True
        assert "courtlistener.com" in result[0].courtlistener_url

    def test_parses_unverified_citation(self):
        data = [{"case_name": "Unknown Case", "citation": "999 U.S. 1", "absolute_url": ""}]
        result = _parse_response(data)
        assert len(result) == 1
        assert result[0].verified is False
        assert result[0].relevance == "not independently verified"

    def test_handles_dict_input(self):
        data = {"case_name": "Single Case", "citation": "1 U.S. 1", "absolute_url": "/opinion/1/"}
        result = _parse_response(data)
        assert len(result) == 1
        assert result[0].verified is True

    def test_handles_empty_list(self):
        assert _parse_response([]) == []

    def test_skips_non_dict_items(self):
        data = [{"case_name": "Good", "citation": "1", "absolute_url": "/x/"}, "bad", 42]
        result = _parse_response(data)
        assert len(result) == 1

    def test_full_url_preserved(self):
        data = [{"case_name": "C", "citation": "1", "absolute_url": "https://example.com/op/1/"}]
        result = _parse_response(data)
        assert result[0].courtlistener_url == "https://example.com/op/1/"


class TestRateLimiter:
    def test_allows_first_request(self):
        rl = _RateLimiter(max_per_minute=5)
        assert rl.acquire() == 0.0

    def test_blocks_when_at_limit(self):
        rl = _RateLimiter(max_per_minute=2)
        rl.acquire()
        rl.acquire()
        wait = rl.acquire()
        assert wait > 0.0


class TestCourtListenerClient:
    @pytest.fixture()
    def client(self):
        return CourtListenerClient(api_key="test-key")

    @pytest.mark.asyncio()
    async def test_empty_text_returns_empty(self, client):
        result = await client.verify_citations("")
        assert result == []

    @pytest.mark.asyncio()
    async def test_whitespace_text_returns_empty(self, client):
        result = await client.verify_citations("   ")
        assert result == []

    @pytest.mark.asyncio()
    async def test_successful_verification(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = [
            {
                "case_name": "Tinker v. Des Moines",
                "citation": "393 U.S. 503",
                "absolute_url": "/opinion/12345/tinker/",
            }
        ]

        with patch("osint_core.services.courtlistener.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await client.verify_citations("See Tinker v. Des Moines, 393 U.S. 503")

        assert len(result) == 1
        assert result[0].verified is True
        assert result[0].case_name == "Tinker v. Des Moines"

    @pytest.mark.asyncio()
    async def test_timeout_returns_unverified(self, client):
        with patch("osint_core.services.courtlistener.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await client.verify_citations("Some legal text")

        assert len(result) == 1
        assert result[0].verified is False
        assert "timed out" in result[0].relevance

    @pytest.mark.asyncio()
    async def test_http_error_returns_empty(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "rate limited", request=MagicMock(), response=mock_response,
            ),
        )

        with patch("osint_core.services.courtlistener.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await client.verify_citations("Some text")

        assert result == []

    @pytest.mark.asyncio()
    async def test_sends_auth_header(self, client):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = []

        with patch("osint_core.services.courtlistener.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            await client.verify_citations("Test text")

        call_kwargs = mock_client.post.call_args
        assert call_kwargs.kwargs["headers"]["Authorization"] == "Token test-key"

    @pytest.mark.asyncio()
    async def test_truncates_long_text(self, client):
        long_text = "x" * 100_000
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = []

        with patch("osint_core.services.courtlistener.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            await client.verify_citations(long_text)

        call_kwargs = mock_client.post.call_args
        sent_text = call_kwargs.kwargs["data"]["text"]
        assert len(sent_text) == 64_000
