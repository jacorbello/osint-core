"""Shared LLM client — routes requests to Groq or vLLM based on config."""

from __future__ import annotations

from typing import Any

import httpx
import structlog

from osint_core.config import settings

logger = structlog.get_logger()


def active_llm_model() -> str:
    """Return the model identifier for the currently active LLM provider."""
    if settings.llm_provider == "groq" and settings.groq_api_key:
        return settings.groq_model
    return settings.llm_model


async def llm_chat_completion(
    *,
    messages: list[dict[str, str]],
    max_tokens: int | None = None,
    temperature: float | None = None,
    timeout: float = 30.0,
    response_format: dict[str, Any] | None = None,
    json_schema: dict[str, Any] | None = None,
) -> str:
    """Send a chat completion request to the configured LLM provider.

    Returns the raw ``choices[0].message.content`` string.  Callers are
    responsible for parsing JSON or other structured output.

    When ``settings.llm_provider`` is ``"groq"`` and the request fails
    with a 429 or 5xx, automatically retries once against the local vLLM
    instance as a fallback.

    Parameters
    ----------
    json_schema:
        When set (and provider is Groq), enables strict structured output
        via ``response_format: {"type": "json_schema", ...}``.
    response_format:
        Passed through to the API payload directly.  For vLLM this is
        typically ``{"type": "json_object"}``.  Ignored when *json_schema*
        is provided and provider is Groq (json_schema takes precedence).
    """
    use_groq = settings.llm_provider == "groq" and settings.groq_api_key

    if use_groq:
        try:
            return await _call_provider(
                base_url=settings.groq_base_url,
                model=settings.groq_model,
                api_key=settings.groq_api_key,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
                response_format=response_format,
                json_schema=json_schema,
                raise_retryable=True,
            )
        except _RetryableError as exc:
            logger.warning(
                "llm_groq_fallback_to_vllm",
                status=exc.status_code,
                error=str(exc),
            )
            # Fall through to vLLM

    return await _call_provider(
        base_url=settings.vllm_url,
        model=settings.llm_model,
        api_key=None,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        timeout=timeout,
        response_format=response_format,
        json_schema=None,  # vLLM does not support strict json_schema
        raise_retryable=False,
    )


class _RetryableError(Exception):
    """Raised when a provider returns a retryable HTTP status (429/5xx)."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


async def _call_provider(
    *,
    base_url: str,
    model: str,
    api_key: str | None,
    messages: list[dict[str, str]],
    max_tokens: int | None,
    temperature: float | None,
    timeout: float,
    response_format: dict[str, Any] | None,
    json_schema: dict[str, Any] | None,
    raise_retryable: bool = True,
) -> str:
    base = base_url.rstrip("/")
    # Append /v1 if not already present (vLLM URLs typically omit it)
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    url = f"{base}/chat/completions"

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if temperature is not None:
        payload["temperature"] = temperature

    # Structured output: json_schema (Groq strict) takes precedence
    if json_schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "response",
                "strict": True,
                "schema": json_schema,
            },
        }
    elif response_format is not None:
        payload["response_format"] = response_format

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload, headers=headers)

    if raise_retryable and (resp.status_code == 429 or resp.status_code >= 500):
        raise _RetryableError(resp.status_code)

    resp.raise_for_status()
    data = resp.json()

    choices = data.get("choices")
    if not choices or not isinstance(choices, list):
        raise ValueError(
            f"Unexpected LLM response: missing 'choices' (keys: {list(data.keys())})"
        )

    content = choices[0].get("message", {}).get("content")
    if content is None:
        raise ValueError("Unexpected LLM response: choices[0].message.content is absent")

    return content
