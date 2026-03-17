"""NLP enrichment task using OpenAI-compatible LLM for summary, relevance, entities.

NOTE: This file is separate from enrich.py which contains vectorize_event_task
and correlate_event_task.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from osint_core.config import settings
from osint_core.models.event import Event
from osint_core.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_SYSTEM_MESSAGE = (
    "You are an intelligence analyst. Respond with JSON only.\n"
    'Respond with exactly this JSON structure:\n'
    '{"summary": "1-2 sentence English summary of the event",\n'
    '"relevance": "relevant|tangential|irrelevant",\n'
    '"entities": [{"name": "...", "type": "person|organization|location|indicator"}]}'
)

_USER_TEMPLATE = """Event title: {title}
Event metadata: {metadata}

Plan mission: {mission}
Plan keywords: {keywords}"""


async def _call_llm(system: str, user: str) -> dict[str, Any]:
    url = f"{settings.llm_url}/v1/chat/completions"
    payload = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
    raw = resp.json()["choices"][0]["message"]["content"]
    result: dict[str, Any] = json.loads(raw)
    return result


async def _enrich_event_async(event_id: str) -> dict[str, Any]:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        event = await db.get(Event, event_id)
        if event is None:
            await engine.dispose()
            return {"event_id": event_id, "status": "not_found"}

        if event.nlp_relevance and event.nlp_summary:
            await engine.dispose()
            return {"event_id": event_id, "status": "skipped"}

        plan_content: dict[str, Any] = {}
        if event.plan_version:
            plan_content = event.plan_version.content or {}

        enrichment = plan_content.get("enrichment", {})
        if not enrichment.get("nlp_enabled", False):
            await engine.dispose()
            return {"event_id": event_id, "status": "nlp_disabled"}

        mission = enrichment.get("mission", "")
        keywords = plan_content.get("keywords", [])

        user_msg = _USER_TEMPLATE.format(
            title=event.title or "",
            metadata=json.dumps(event.metadata_ or {}, default=str)[:500],
            mission=mission,
            keywords=", ".join(keywords),
        )

        try:
            result = await _call_llm(_SYSTEM_MESSAGE, user_msg)
        except (TimeoutError, httpx.TimeoutException, httpx.HTTPError, json.JSONDecodeError) as e:
            logger.warning("NLP enrichment fallback for %s: %s", event_id, e)
            await engine.dispose()
            return {"event_id": event_id, "status": "fallback"}

        if not event.summary and result.get("summary"):
            event.nlp_summary = result["summary"]

        relevance = result.get("relevance", "")
        if relevance in ("relevant", "tangential", "irrelevant"):
            event.nlp_relevance = relevance

        await db.commit()

    await engine.dispose()
    return {"event_id": event_id, "status": "enriched"}


@celery_app.task(bind=True, name="osint.nlp_enrich_event", max_retries=1)  # type: ignore[untyped-decorator]
def nlp_enrich_task(self: Any, event_id: str) -> dict[str, Any]:
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_enrich_event_async(event_id))
    except Exception as exc:
        logger.exception("NLP enrichment failed for %s", event_id)
        raise self.retry(
            exc=exc, countdown=min(2 ** self.request.retries * 30, 900)
        ) from exc
    finally:
        loop.close()
