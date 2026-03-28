"""NLP enrichment task using vLLM for summary, relevance, entities, ATT&CK techniques.

NOTE: This file is separate from enrich.py which contains vectorize_event_task
and correlate_event_task.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx
from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from osint_core.config import settings
from osint_core.models.event import Event
from osint_core.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_CAL_PLAN_ID = "cal-prospecting"

_VALID_CONSTITUTIONAL_BASES = frozenset({
    "1A-free-speech", "1A-religion", "1A-assembly", "1A-press",
    "14A-due-process", "14A-equal-protection", "parental-rights",
})

_VALID_JURISDICTIONS = frozenset({"CA", "TX", "MN", "DC"})

_SYSTEM_MESSAGE = (
    "You are an intelligence analyst. Respond with JSON only.\n"
    "Respond with exactly this JSON structure:\n"
    '{"summary": "1-2 sentence English summary of the event",\n'
    '"relevance": "relevant|tangential|irrelevant",\n'
    '"entities": [{"name": "...", "type": "person|organization|location|indicator"}],\n'
    '"attack_techniques": [{"id": "T1566", "name": "Phishing"}]}\n'
    "\n"
    "For attack_techniques, classify the event using MITRE ATT&CK technique IDs.\n"
    "Common techniques include: T1566 Phishing, T1190 Exploit Public-Facing Application,\n"
    "T1059 Command and Scripting Interpreter, T1071 Application Layer Protocol,\n"
    "T1486 Data Encrypted for Impact, T1070 Indicator Removal, T1110 Brute Force,\n"
    "T1027 Obfuscated Files or Information, T1078 Valid Accounts, T1562 Impair Defenses,\n"
    "T1595 Active Scanning, T1583 Acquire Infrastructure, T1498 Network Denial of Service,\n"
    "T1557 Adversary-in-the-Middle, T1040 Network Sniffing.\n"
    "Return an empty list if no techniques apply."
)

_CAL_SYSTEM_MESSAGE = (
    "You are a constitutional rights analyst for The Center For American Liberty. "
    "Respond with JSON only.\n"
    "Respond with exactly this JSON structure:\n"
    '{"summary": "1-2 sentence English summary of the event",\n'
    '"relevance": "relevant|tangential|irrelevant",\n'
    '"entities": [{"name": "...", "type": '
    '"person|organization|location|indicator|official|affected_individual"}],\n'
    '"constitutional_basis": ["1A-free-speech"],\n'
    '"lead_type": "incident|policy",\n'
    '"institution": "Name of the state university or institution involved",\n'
    '"jurisdiction": "CA|TX|MN|DC"}\n'
    "\n"
    "For constitutional_basis, classify using one or more of these labels:\n"
    "1A-free-speech, 1A-religion, 1A-assembly, 1A-press, "
    "14A-due-process, 14A-equal-protection, parental-rights.\n"
    "Return an empty list if no constitutional basis applies.\n"
    "\n"
    "For lead_type, classify as 'incident' (a specific event involving individuals) "
    "or 'policy' (a rule, regulation, or institutional policy change).\n"
    "\n"
    "For institution, extract the name of the university or educational institution. "
    "Return null if no institution is identified.\n"
    "\n"
    "For jurisdiction, extract the state/district: CA, TX, MN, or DC. "
    "Return null if the jurisdiction cannot be determined.\n"
    "\n"
    "For entities, use extended types: person, organization, location, indicator, "
    "official (university administrators, government officials), "
    "affected_individual (students, faculty, staff whose rights are at issue)."
)

_USER_TEMPLATE = """Event title: {title}
Event metadata: {metadata}

Plan mission: {mission}
Plan keywords: {keywords}"""


def _strip_markdown_fences(text: str) -> str:
    """Extract JSON from markdown code fences if present."""
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return match.group(1)
    return text.strip()


def _validate_attack_techniques(raw: Any) -> list[dict[str, str]]:
    """Validate and normalize attack_techniques from the LLM response.

    Returns a list of dicts with ``id`` and ``name`` keys.  Invalid or
    missing entries are silently dropped so that the enrichment pipeline
    never fails due to unexpected LLM output.
    """
    if not isinstance(raw, list):
        return []
    validated: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        tid = item.get("id")
        tname = item.get("name")
        if isinstance(tid, str) and tid:
            validated.append({
                "id": tid,
                "name": tname if isinstance(tname, str) else "",
            })
    return validated


def _validate_constitutional_fields(result: dict[str, Any]) -> dict[str, Any]:
    """Extract and validate CAL constitutional classification fields.

    Returns a dict with validated ``constitutional_basis``, ``lead_type``,
    ``institution``, and ``jurisdiction`` suitable for storing in event metadata.
    """
    raw_basis = result.get("constitutional_basis")
    basis = (
        [b for b in raw_basis if isinstance(b, str) and b in _VALID_CONSTITUTIONAL_BASES]
        if isinstance(raw_basis, list) else []
    )

    raw_lead = result.get("lead_type")
    lead_type = raw_lead if isinstance(raw_lead, str) and raw_lead in ("incident", "policy") else None

    raw_inst = result.get("institution")
    institution = raw_inst if isinstance(raw_inst, str) and raw_inst else None

    raw_juris = result.get("jurisdiction")
    jurisdiction = raw_juris if isinstance(raw_juris, str) and raw_juris in _VALID_JURISDICTIONS else None

    return {
        "constitutional_basis": basis,
        "lead_type": lead_type,
        "institution": institution,
        "jurisdiction": jurisdiction,
    }


async def _call_vllm(
    prompt: str,
    *,
    system_message: str | None = None,
    max_tokens: int = 500,
) -> dict[str, Any]:
    url = f"{settings.vllm_url}/v1/chat/completions"
    payload = {
        "model": settings.llm_model,
        "messages": [
            {"role": "system", "content": system_message or _SYSTEM_MESSAGE},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.1,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
    data = resp.json()
    choices = data.get("choices")
    if not choices or not isinstance(choices, list):
        raise ValueError(
            f"Unexpected vLLM response shape: missing or empty 'choices' (got: {list(data.keys())})"
        )
    content = choices[0].get("message", {}).get("content")
    if content is None:
        raise ValueError(
            "Unexpected vLLM response shape: 'choices[0].message.content' is absent"
        )
    result: dict[str, Any] = json.loads(_strip_markdown_fences(content))
    return result


async def _enrich_event_async(event_id: str) -> dict[str, Any]:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        event = await db.get(Event, event_id)
        if event is None:
            logger.warning("NLP enrich: event %s not found in DB", event_id)
            await engine.dispose()
            return {"event_id": event_id, "status": "not_found"}

        if event.nlp_relevance and event.nlp_summary:
            await engine.dispose()
            return {"event_id": event_id, "status": "skipped"}

        plan_content: dict[str, Any] = {}
        plan_id: str | None = None
        if event.plan_version:
            plan_content = event.plan_version.content or {}
            plan_id = event.plan_version.plan_id
        else:
            logger.warning(
                "NLP enrich: event %s has no plan_version (plan_version_id=%s)",
                event_id, event.plan_version_id,
            )

        enrichment = plan_content.get("enrichment", {})
        if not enrichment.get("nlp_enabled", False):
            logger.info(
                "NLP enrich: skipping event %s — nlp_enabled is false "
                "(plan_version_id=%s, has_plan_version=%s)",
                event_id, event.plan_version_id, event.plan_version is not None,
            )
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

        # Select prompt and token budget based on plan
        is_cal = plan_id == _CAL_PLAN_ID
        system_msg = _CAL_SYSTEM_MESSAGE if is_cal else None
        vllm_max_tokens = 800 if is_cal else 500

        try:
            result = await _call_vllm(
                user_msg, system_message=system_msg, max_tokens=vllm_max_tokens,
            )
        except (
            TimeoutError,
            httpx.TimeoutException,
            httpx.HTTPError,
            json.JSONDecodeError,
            ValueError,
        ) as e:
            logger.warning("NLP enrichment fallback for %s: %s", event_id, e)
            await engine.dispose()
            return {"event_id": event_id, "status": "fallback"}

        if result.get("summary"):
            event.nlp_summary = result["summary"]

        relevance = result.get("relevance", "")
        if relevance in ("relevant", "tangential", "irrelevant"):
            event.nlp_relevance = relevance

        meta = dict(event.metadata_ or {})

        if is_cal:
            # Store CAL constitutional classification in metadata
            cal_fields = _validate_constitutional_fields(result)
            meta["constitutional_basis"] = cal_fields["constitutional_basis"]
            meta["lead_type"] = cal_fields["lead_type"]
            meta["institution"] = cal_fields["institution"]
            meta["jurisdiction"] = cal_fields["jurisdiction"]
        else:
            # Store ATT&CK technique classifications in event metadata
            techniques = _validate_attack_techniques(result.get("attack_techniques"))
            meta["attack_techniques"] = techniques

        event.metadata_ = meta

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
