"""Brief generator — produce intel briefs via vLLM or Jinja2 template fallback."""

from __future__ import annotations

import importlib.resources
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from jinja2 import Template

logger = structlog.get_logger()

_SYSTEM_PROMPT = (
    "You are an intelligence analyst. Given the following OSINT context, "
    "produce a concise, structured intelligence brief in Markdown format. "
    "Include key findings, indicators of compromise, and recommended actions."
)


def _load_template() -> Template:
    """Load the default brief Jinja2 template from package resources."""
    template_files = importlib.resources.files("osint_core.templates")
    template_file = template_files.joinpath("brief_default.md.j2")
    return Template(template_file.read_text(encoding="utf-8"))


class BriefGenerator:
    """Generate intelligence briefs using vLLM or a Jinja2 template fallback.

    Args:
        vllm_url: Base URL for the vLLM API (e.g. ``http://vllm-inference:8000``).
        llm_model: Model identifier (e.g. ``meta-llama/Llama-3.2-3B-Instruct``).
        llm_available: Whether to attempt vLLM generation before falling back.
    """

    def __init__(
        self,
        *,
        vllm_url: str = "",
        llm_model: str = "",
        llm_available: bool = True,
    ) -> None:
        self._vllm_url = vllm_url.rstrip("/") if vllm_url else ""
        self._llm_model = llm_model
        self._llm_available = llm_available and bool(vllm_url)
        self._template = _load_template()

    # ------------------------------------------------------------------
    # Template generation
    # ------------------------------------------------------------------

    def generate_from_template(
        self,
        *,
        title: str,
        events: list[dict[str, Any]],
        indicators: list[dict[str, Any]],
        entities: list[dict[str, Any]],
    ) -> str:
        """Render a brief using the Jinja2 template.

        Args:
            title: Brief title / headline.
            events: List of event dicts (title, severity, score, source_id, occurred_at).
            indicators: List of indicator dicts (value, type).
            entities: List of entity dicts (name, entity_type).

        Returns:
            Rendered Markdown string.
        """
        summary_parts: list[str] = []
        if events:
            summary_parts.append(f"{len(events)} event(s) analysed.")
        if indicators:
            summary_parts.append(f"{len(indicators)} indicator(s) of compromise identified.")
        if entities:
            summary_parts.append(f"{len(entities)} entity/entities referenced.")
        summary_text = " ".join(summary_parts) if summary_parts else "No data available."

        md = self._template.render(
            title=title,
            generated_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            generated_by="template",
            events=events,
            indicators=indicators,
            entities=entities,
            summary_text=summary_text,
        )

        logger.info("brief_generated_from_template", title=title, events=len(events))
        return md

    # ------------------------------------------------------------------
    # vLLM generation
    # ------------------------------------------------------------------

    async def generate_from_vllm(self, *, query: str, context: str) -> str:
        """Call the vLLM ``/v1/chat/completions`` endpoint to produce an AI brief.

        Args:
            query: The user's natural-language query describing the brief scope.
            context: Assembled context text (events, indicators, entities).

        Returns:
            Generated Markdown string from the LLM.

        Raises:
            httpx.HTTPStatusError: If the vLLM API returns a non-2xx status.
            httpx.ConnectError: If the vLLM service is unreachable.
        """
        prompt = f"{_SYSTEM_PROMPT}\n\nQuery: {query}\n\nContext:\n{context}"

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self._vllm_url}/v1/chat/completions",
                json={
                    "model": self._llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
            )
            response.raise_for_status()

        data = response.json()
        choices = data.get("choices")
        if not choices or not isinstance(choices, list):
            raise ValueError(
                "Unexpected vLLM response shape: "
                f"missing or empty 'choices' (got: {list(data.keys())})"
            )
        message = choices[0].get("message", {})
        content = message.get("content")
        if content is None:
            raise ValueError(
                "Unexpected vLLM response shape: 'choices[0].message.content' is absent"
            )
        text: str = content

        logger.info(
            "brief_generated_from_vllm",
            model=self._llm_model,
            response_length=len(text),
        )
        return text

    # ------------------------------------------------------------------
    # Unified generation (vLLM first, template fallback)
    # ------------------------------------------------------------------

    async def generate(
        self,
        *,
        query: str,
        events: list[dict[str, Any]],
        indicators: list[dict[str, Any]],
        entities: list[dict[str, Any]],
    ) -> str:
        """Generate a brief -- try vLLM first, fall back to template on failure.

        Args:
            query: Natural-language query describing the brief scope.
            events: List of event dicts.
            indicators: List of indicator dicts.
            entities: List of entity dicts.

        Returns:
            Markdown string from either vLLM or the template.
        """
        title = query or "Intelligence Brief"

        if self._llm_available:
            try:
                context = self._build_context(events, indicators, entities)
                return await self.generate_from_vllm(query=query, context=context)
            except (
                httpx.HTTPStatusError,
                httpx.ConnectError,
                httpx.TimeoutException,
                ValueError,
            ) as exc:
                logger.warning(
                    "vllm_generation_failed_falling_back_to_template",
                    error=str(exc),
                )

        return self.generate_from_template(
            title=title,
            events=events,
            indicators=indicators,
            entities=entities,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_context(
        events: list[dict[str, Any]],
        indicators: list[dict[str, Any]],
        entities: list[dict[str, Any]],
    ) -> str:
        """Assemble a plain-text context block for the LLM prompt."""
        lines: list[str] = []

        if events:
            lines.append("Events:")
            for evt in events:
                lines.append(
                    f"  - {evt.get('title', 'Untitled')} "
                    f"(severity={evt.get('severity', 'unknown')}, "
                    f"score={evt.get('score', 'N/A')})"
                )

        if indicators:
            lines.append("Indicators:")
            for ioc in indicators:
                lines.append(f"  - {ioc.get('value', '?')} ({ioc.get('type', '?')})")

        if entities:
            lines.append("Entities:")
            for ent in entities:
                lines.append(
                    f"  - {ent.get('name', '?')} ({ent.get('entity_type', '?')})"
                )

        return "\n".join(lines)
