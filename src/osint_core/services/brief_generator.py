"""Brief generator — produce intel briefs via Ollama LLM or Jinja2 template fallback."""

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
    """Generate intelligence briefs using Ollama or a Jinja2 template fallback.

    Args:
        ollama_url: Base URL for the Ollama API (e.g. ``http://ollama:11434``).
        ollama_model: Model identifier (e.g. ``llama3.1:8b``).
        ollama_available: Whether to attempt Ollama generation before falling back.
    """

    def __init__(
        self,
        *,
        ollama_url: str = "",
        ollama_model: str = "",
        ollama_available: bool = True,
    ) -> None:
        self._ollama_url = ollama_url.rstrip("/") if ollama_url else ""
        self._ollama_model = ollama_model
        self._ollama_available = ollama_available and bool(ollama_url)
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
    # Ollama generation
    # ------------------------------------------------------------------

    async def generate_from_ollama(self, *, query: str, context: str) -> str:
        """Call the Ollama ``/api/generate`` endpoint to produce an AI brief.

        Args:
            query: The user's natural-language query describing the brief scope.
            context: Assembled context text (events, indicators, entities).

        Returns:
            Generated Markdown string from the LLM.

        Raises:
            httpx.HTTPStatusError: If the Ollama API returns a non-2xx status.
            httpx.ConnectError: If the Ollama service is unreachable.
        """
        prompt = f"{_SYSTEM_PROMPT}\n\nQuery: {query}\n\nContext:\n{context}"

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self._ollama_url}/api/generate",
                json={
                    "model": self._ollama_model,
                    "prompt": prompt,
                    "stream": False,
                },
            )
            response.raise_for_status()

        data = response.json()
        text: str = data.get("response", "")

        logger.info(
            "brief_generated_from_ollama",
            model=self._ollama_model,
            response_length=len(text),
        )
        return text

    # ------------------------------------------------------------------
    # Unified generation (Ollama first, template fallback)
    # ------------------------------------------------------------------

    async def generate(
        self,
        *,
        query: str,
        events: list[dict[str, Any]],
        indicators: list[dict[str, Any]],
        entities: list[dict[str, Any]],
    ) -> str:
        """Generate a brief -- try Ollama first, fall back to template on failure.

        Args:
            query: Natural-language query describing the brief scope.
            events: List of event dicts.
            indicators: List of indicator dicts.
            entities: List of entity dicts.

        Returns:
            Markdown string from either Ollama or the template.
        """
        title = query or "Intelligence Brief"

        if self._ollama_available:
            try:
                context = self._build_context(events, indicators, entities)
                return await self.generate_from_ollama(query=query, context=context)
            except (httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException) as exc:
                logger.warning(
                    "ollama_generation_failed_falling_back_to_template",
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
