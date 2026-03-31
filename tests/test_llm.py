"""Tests for the shared LLM client."""

import json
from unittest.mock import patch

import httpx
import pytest

from osint_core.llm import llm_chat_completion

_MESSAGES = [{"role": "user", "content": "Hello"}]

_VALID_RESPONSE = {
    "choices": [{"message": {"content": '{"result": "ok"}'}}],
}


def _mock_settings(**overrides):
    """Return a patched settings object with defaults + overrides."""
    defaults = {
        "llm_provider": "vllm",
        "vllm_url": "http://localhost:8001",
        "llm_model": "test-model",
        "groq_api_key": "",
        "groq_base_url": "https://api.groq.com/openai/v1",
        "groq_model": "openai/gpt-oss-20b",
    }
    defaults.update(overrides)

    class FakeSettings:
        pass

    s = FakeSettings()
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


@pytest.mark.asyncio
async def test_vllm_path(respx_mock):
    """vLLM provider sends to local URL without auth header."""
    s = _mock_settings(llm_provider="vllm")
    route = respx_mock.post("http://localhost:8001/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_VALID_RESPONSE),
    )

    with patch("osint_core.llm.settings", s):
        content = await llm_chat_completion(
            messages=_MESSAGES, timeout=5.0,
        )

    assert content == '{"result": "ok"}'
    req = route.calls[0].request
    assert "Authorization" not in req.headers


@pytest.mark.asyncio
async def test_groq_path_with_auth(respx_mock):
    """Groq provider sends to Groq URL with Bearer auth."""
    s = _mock_settings(llm_provider="groq", groq_api_key="sk-test")
    route = respx_mock.post(
        "https://api.groq.com/openai/v1/chat/completions",
    ).mock(return_value=httpx.Response(200, json=_VALID_RESPONSE))

    with patch("osint_core.llm.settings", s):
        content = await llm_chat_completion(
            messages=_MESSAGES, timeout=5.0,
        )

    assert content == '{"result": "ok"}'
    req = route.calls[0].request
    assert req.headers["Authorization"] == "Bearer sk-test"


@pytest.mark.asyncio
async def test_groq_json_schema(respx_mock):
    """Groq path sends strict json_schema in response_format."""
    s = _mock_settings(llm_provider="groq", groq_api_key="sk-test")
    route = respx_mock.post(
        "https://api.groq.com/openai/v1/chat/completions",
    ).mock(return_value=httpx.Response(200, json=_VALID_RESPONSE))

    schema = {"type": "object", "properties": {"x": {"type": "string"}}}

    with patch("osint_core.llm.settings", s):
        await llm_chat_completion(
            messages=_MESSAGES, json_schema=schema, timeout=5.0,
        )

    body = json.loads(route.calls[0].request.content)
    rf = body["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"] == schema


@pytest.mark.asyncio
async def test_groq_429_falls_back_to_vllm(respx_mock):
    """On Groq 429, retries against vLLM and succeeds."""
    s = _mock_settings(llm_provider="groq", groq_api_key="sk-test")
    respx_mock.post(
        "https://api.groq.com/openai/v1/chat/completions",
    ).mock(return_value=httpx.Response(429, text="rate limited"))

    respx_mock.post(
        "http://localhost:8001/v1/chat/completions",
    ).mock(return_value=httpx.Response(200, json=_VALID_RESPONSE))

    with patch("osint_core.llm.settings", s):
        content = await llm_chat_completion(
            messages=_MESSAGES, timeout=5.0,
        )

    assert content == '{"result": "ok"}'


@pytest.mark.asyncio
async def test_groq_500_falls_back_to_vllm(respx_mock):
    """On Groq 500, retries against vLLM."""
    s = _mock_settings(llm_provider="groq", groq_api_key="sk-test")
    respx_mock.post(
        "https://api.groq.com/openai/v1/chat/completions",
    ).mock(return_value=httpx.Response(500, text="internal error"))

    respx_mock.post(
        "http://localhost:8001/v1/chat/completions",
    ).mock(return_value=httpx.Response(200, json=_VALID_RESPONSE))

    with patch("osint_core.llm.settings", s):
        content = await llm_chat_completion(
            messages=_MESSAGES, timeout=5.0,
        )

    assert content == '{"result": "ok"}'


@pytest.mark.asyncio
async def test_both_fail_raises(respx_mock):
    """When both Groq and vLLM fail, the error propagates."""
    s = _mock_settings(llm_provider="groq", groq_api_key="sk-test")
    respx_mock.post(
        "https://api.groq.com/openai/v1/chat/completions",
    ).mock(return_value=httpx.Response(429, text="rate limited"))

    respx_mock.post(
        "http://localhost:8001/v1/chat/completions",
    ).mock(return_value=httpx.Response(500, text="vllm down"))

    with patch("osint_core.llm.settings", s), pytest.raises(httpx.HTTPStatusError):
        await llm_chat_completion(messages=_MESSAGES, timeout=5.0)


@pytest.mark.asyncio
async def test_vllm_response_format_passthrough(respx_mock):
    """vLLM path passes response_format through as-is."""
    s = _mock_settings(llm_provider="vllm")
    route = respx_mock.post(
        "http://localhost:8001/v1/chat/completions",
    ).mock(return_value=httpx.Response(200, json=_VALID_RESPONSE))

    with patch("osint_core.llm.settings", s):
        await llm_chat_completion(
            messages=_MESSAGES,
            response_format={"type": "json_object"},
            timeout=5.0,
        )

    body = json.loads(route.calls[0].request.content)
    assert body["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_groq_without_api_key_falls_to_vllm(respx_mock):
    """Groq provider without API key falls back to vLLM."""
    s = _mock_settings(llm_provider="groq", groq_api_key="")
    route = respx_mock.post(
        "http://localhost:8001/v1/chat/completions",
    ).mock(return_value=httpx.Response(200, json=_VALID_RESPONSE))

    with patch("osint_core.llm.settings", s):
        content = await llm_chat_completion(
            messages=_MESSAGES, timeout=5.0,
        )

    assert content == '{"result": "ok"}'
    assert route.call_count == 1
