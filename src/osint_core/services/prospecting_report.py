"""Prospecting report generator — orchestrates lead selection, narrative
generation, citation verification, and PDF rendering."""

from __future__ import annotations

import asyncio
import importlib.resources
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import case, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from osint_core.llm import llm_chat_completion
from osint_core.models.lead import Lead
from osint_core.models.report import Report
from osint_core.services.courtlistener import CourtListenerClient
from osint_core.services.pdf_export import upload_pdf_to_minio

logger = structlog.get_logger()

_CAL_PLAN_ID = "cal-prospecting"

_SKIPPED_STATUSES = frozenset({
    "extraction_failed", "non_english", "no_content",
    "no_source_material", "failed",
})


def _filter_reportable_leads(leads: list[Lead]) -> list[Lead]:
    """Filter out non-actionable and skipped leads from main report body."""
    return [
        lead for lead in leads
        if getattr(lead, "analysis_status", None) not in ("not_actionable", *_SKIPPED_STATUSES)
    ]


def _extract_source_url(lead: Lead) -> str:
    """Extract primary source URL from lead citations."""
    citations_data = lead.citations or {}
    source_cites = citations_data.get("source_citations", [])
    return source_cites[0].get("url", "") if source_cites else ""


def _group_skipped_leads(leads: list[Lead]) -> dict[str, list[dict[str, Any]]]:
    """Group skipped leads by failure status for the appendix."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for lead in leads:
        status = getattr(lead, "analysis_status", None)
        if status not in _SKIPPED_STATUSES:
            continue
        entry = {
            "title": lead.title or "",
            "institution": lead.institution or "",
            "source_url": _extract_source_url(lead),
        }
        groups.setdefault(status, []).append(entry)
    return groups

_NARRATIVE_SYSTEM_PROMPT = (
    "You are a constitutional rights analyst for The Center For American Liberty. "
    "Given the following lead data, produce structured narrative sections for a legal "
    "prospecting report. IMPORTANT: Only cite sources that appear in the provided "
    "source material. Do not hallucinate or invent any citations.\n\n"
    "Respond with JSON only. Structure:\n"
    '{"executive_summary": "...", "constitutional_analysis": "...", '
    '"recommendation": "...", "parties": "...", "evidence": "...", '
    '"jurisdiction_analysis": "...", "time_sensitivity": "...", '
    '"affected_population": "...", "policy_text": "...", "precedents": "..."}'
)

_NARRATIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "executive_summary": {"type": "string"},
        "constitutional_analysis": {"type": "string"},
        "recommendation": {"type": "string"},
        "parties": {"type": "string"},
        "evidence": {"type": "string"},
        "jurisdiction_analysis": {"type": "string"},
        "time_sensitivity": {"type": "string"},
        "affected_population": {"type": "string"},
        "policy_text": {"type": "string"},
        "precedents": {"type": "string"},
    },
    "required": [
        "executive_summary",
        "constitutional_analysis",
        "recommendation",
        "parties",
        "evidence",
        "jurisdiction_analysis",
        "time_sensitivity",
        "affected_population",
        "policy_text",
        "precedents",
    ],
    "additionalProperties": False,
}


@dataclass
class ReportResult:
    """Result of a report generation cycle."""

    pdf_bytes: bytes
    lead_count: int
    artifact_uri: str
    report_date: str


async def _select_reportable_leads(db: AsyncSession) -> list[Lead]:
    """Select leads that need reporting.

    Criteria: status='new' OR (status='reviewing' AND last_updated_at > reported_at)
    """
    severity_order = case(
        (Lead.severity == "critical", 0),
        (Lead.severity == "high", 1),
        (Lead.severity == "medium", 2),
        (Lead.severity == "low", 3),
        else_=4,
    )
    stmt = (
        select(Lead)
        .where(
            Lead.plan_id == _CAL_PLAN_ID,
            or_(
                Lead.status == "new",
                (Lead.status == "reviewing")
                & (Lead.last_updated_at > Lead.reported_at),
            ),
        )
        .order_by(severity_order, Lead.confidence.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _generate_narrative(lead: Lead) -> dict[str, Any]:
    """Generate narrative sections for a lead via the configured LLM provider."""
    lead_data = {
        "title": lead.title,
        "summary": lead.summary,
        "lead_type": lead.lead_type,
        "institution": lead.institution,
        "jurisdiction": lead.jurisdiction,
        "constitutional_basis": lead.constitutional_basis,
        "severity": lead.severity,
        "confidence": lead.confidence,
    }

    user_msg = f"Lead data:\n{json.dumps(lead_data, default=str)}"

    try:
        content = await llm_chat_completion(
            messages=[
                {"role": "system", "content": _NARRATIVE_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=1500,
            temperature=0.2,
            timeout=30.0,
            response_format={"type": "json_object"},
            json_schema=_NARRATIVE_SCHEMA,
        )
    except Exception as exc:
        logger.warning("narrative_generation_failed", lead_id=str(lead.id), error=str(exc))
        return _fallback_narrative(lead)

    try:
        result = _extract_json(content)
        if result is None:
            logger.warning(
                "narrative_parse_failed",
                lead_id=str(lead.id),
                content_preview=content[:200] if content else "",
            )
            return _fallback_narrative(lead)
        return result
    except (json.JSONDecodeError, ValueError, KeyError, IndexError) as exc:
        logger.warning("narrative_parse_failed", lead_id=str(lead.id), error=str(exc))
        return _fallback_narrative(lead)


_JSON_FENCE_RE = re.compile(
    r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL,
)


def _extract_json(content: str) -> dict[str, Any] | None:
    """Try to parse JSON from LLM output, handling common formatting issues.

    Handles: raw JSON, markdown-fenced JSON, JSON embedded in prose.
    Returns None if no valid JSON object can be extracted.
    """
    if not content or not content.strip():
        return None

    text = content.strip()

    # 1. Direct parse (ideal case — response_format: json_object)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    # 2. Strip markdown code fences (```json ... ```)
    fence_match = _JSON_FENCE_RE.search(text)
    if fence_match:
        try:
            parsed = json.loads(fence_match.group(1))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    # 3. Scan for balanced { ... } blocks in prose and try each as JSON
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escape = False
        end = None

        for i in range(start, len(text)):
            ch = text[i]

            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue

            if ch == '"':
                in_string = True
                continue

            if ch == "{":
                depth += 1
            elif ch == "}" and depth > 0:
                depth -= 1
                if depth == 0:
                    end = i
                    break

        if end is not None:
            candidate = text[start : end + 1]
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass

        start = text.find("{", start + 1)

    return None


def _build_deep_analysis_context(lead: Lead) -> dict[str, Any]:
    """Build template context from deep analysis results."""
    analysis = lead.deep_analysis or {}

    # Use analysis content to determine rendering path, not lead_type —
    # NLP triage frequently misclassifies policy documents as incidents,
    # but the deep analyzer uses source-based dispatch and stores
    # provisions for all archived policy documents regardless of lead_type.
    has_provisions = bool(analysis.get("provisions"))
    if has_provisions:
        provisions = analysis.get("provisions", [])
        return {
            "has_deep_analysis": True,
            "lead_type": "policy",
            "title": lead.title,
            "institution": lead.institution,
            "jurisdiction": lead.jurisdiction,
            "severity": lead.severity,
            "confidence": lead.confidence,
            "constitutional_basis": lead.constitutional_basis,
            "document_summary": analysis.get("document_summary", ""),
            "overall_assessment": analysis.get("overall_assessment", ""),
            "actionable": analysis.get("actionable", False),
            "provisions": provisions,
            "source_citations": [],
            "legal_citations": [],
        }
    else:
        # Incident
        return {
            "has_deep_analysis": True,
            "lead_type": "incident",
            "title": lead.title,
            "institution": lead.institution or analysis.get("institution", ""),
            "jurisdiction": lead.jurisdiction,
            "severity": lead.severity,
            "confidence": lead.confidence,
            "constitutional_basis": lead.constitutional_basis,
            "incident_summary": analysis.get("incident_summary", ""),
            "rights_violated": analysis.get("rights_violated", []),
            "individuals_identified": analysis.get("individuals_identified", []),
            "corroboration_strength": analysis.get("corroboration_strength", ""),
            "corroboration_notes": analysis.get("corroboration_notes", ""),
            "actionable": analysis.get("actionable", False),
            "source_citations": [],
            "legal_citations": [],
        }


def _fallback_narrative(lead: Lead) -> dict[str, str]:
    """Produce minimal narrative when LLM is unavailable."""
    return {
        "executive_summary": lead.summary or lead.title or "",
        "constitutional_analysis": ", ".join(lead.constitutional_basis or []),
        "recommendation": "Requires further review.",
    }


def _render_pdf_html(context: dict[str, Any]) -> str:
    """Render the prospecting report HTML from Jinja2 template."""
    template_dir = str(
        importlib.resources.files("osint_core") / "templates"
    )
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=True)
    template = env.get_template("prospecting_report.html")
    return template.render(**context)


class ProspectingReportGenerator:
    """Orchestrates the full prospecting report pipeline."""

    def __init__(self, *, courtlistener: CourtListenerClient | None = None) -> None:
        self._courtlistener = courtlistener or CourtListenerClient()

    async def generate_report(self, db: AsyncSession) -> ReportResult | None:
        """Generate a prospecting report for all reportable leads.

        Returns None if no reportable leads exist.
        """
        all_leads = await _select_reportable_leads(db)
        if not all_leads:
            logger.info("prospecting_report_no_leads")
            return None

        now = datetime.now(UTC)
        ct_now = now.astimezone(ZoneInfo("America/Chicago"))
        tz_abbr = ct_now.strftime("%Z")  # CST or CDT depending on DST
        report_date = ct_now.strftime(f"%B %d, %Y — %I:%M %p {tz_abbr}")

        skipped = _group_skipped_leads(all_leads)
        leads = _filter_reportable_leads(all_leads)

        # Build lead contexts with narrative sections
        lead_contexts = []
        rendered_lead_ids: set[Any] = set()
        all_source_citations: list[str] = []
        all_legal_citations: list[dict[str, Any]] = []

        for lead in leads:
            # Skip non-English policy translations (UC multilingual docs).
            title = lead.title or ""
            non_en_prefixes = ("Pansamantalang ", "Laban sa ", "Póliza ", "Política ")
            has_cjk = any(ord(c) > 0x2E80 for c in title)
            stripped = title.removeprefix(
                "[University of California System] View Policy"
            )
            has_non_en_prefix = stripped.startswith(non_en_prefixes)
            if has_cjk or has_non_en_prefix:
                continue

            analysis_status = getattr(lead, "analysis_status", None)
            da = lead.deep_analysis if hasattr(lead, "deep_analysis") else None

            # Skip leads that deep analysis determined are not actionable
            if analysis_status == "completed" and da:
                if not da.get("actionable", True):
                    continue
                lead_ctx = _build_deep_analysis_context(lead)
                # Enrich with source URL and legal citations from citations field
                citations_data = lead.citations or {}
                source_cites = citations_data.get("source_citations", [])
                lead_ctx["source_url"] = source_cites[0].get("url", "") if source_cites else ""
                legal_cites = citations_data.get("legal_citations", [])
                lead_ctx["legal_citations"] = legal_cites
                # Accumulate into global citation lists for the appendix
                all_source_citations.extend(
                    c.get("url", "") for c in source_cites if c.get("url")
                )
                all_legal_citations.extend(legal_cites)
            elif analysis_status in ("completed", "no_source_material", "failed"):
                # Deep analysis ran but produced nothing useful — skip
                continue
            else:
                # Existing shallow narrative path
                sections = await _generate_narrative(lead)

                # Source citations from lead metadata
                shallow_cites: list[str] = []
                if lead.citations:
                    raw = lead.citations.get("source_citations") or lead.citations.get(
                        "sources", [],
                    )
                    for item in raw:
                        if isinstance(item, dict):
                            url = item.get("url", "")
                            if url:
                                shallow_cites.append(url)
                        elif item:
                            shallow_cites.append(item)
                    all_source_citations.extend(shallow_cites)

                # Verify legal citations via CourtListener
                lead_legal_citations: list[dict[str, Any]] = []
                try:
                    narrative_text = " ".join(
                        str(v) for v in sections.values() if v
                    )
                    if not self._courtlistener.api_key:
                        logger.debug(
                            "courtlistener_skipped_no_api_key",
                            lead_id=str(lead.id),
                        )
                        verified: list[Any] = []
                    else:
                        verified = await asyncio.wait_for(
                            self._courtlistener.verify_citations(narrative_text),
                            timeout=10.0,
                        )
                    for vc in verified:
                        cite_dict: dict[str, Any] = {
                            "case_name": vc.case_name,
                            "citation": vc.citation,
                            "courtlistener_url": vc.courtlistener_url,
                            "verified": vc.verified,
                            "relevance": vc.relevance,
                            "holding_summary": vc.holding_summary,
                        }
                        lead_legal_citations.append(cite_dict)
                        all_legal_citations.append(cite_dict)
                except Exception as exc:
                    logger.warning(
                        "courtlistener_verification_failed",
                        lead_id=str(lead.id),
                        error=str(exc),
                    )

                # Extract source URL from source_citations field
                citations_data = lead.citations or {}
                src_citation_list = citations_data.get("source_citations", [])
                source_url = src_citation_list[0].get("url", "") if src_citation_list else ""

                lead_ctx = {
                    "has_deep_analysis": False,
                    "lead_type": lead.lead_type,
                    "title": lead.title,
                    "summary": lead.summary,
                    "constitutional_basis": lead.constitutional_basis or [],
                    "jurisdiction": lead.jurisdiction,
                    "institution": lead.institution,
                    "severity": lead.severity,
                    "confidence": lead.confidence,
                    "sections": sections,
                    "source_citations": shallow_cites,
                    "legal_citations": lead_legal_citations,
                    "source_url": source_url,
                }

            lead_contexts.append(lead_ctx)
            rendered_lead_ids.add(lead.id)

        # Build summary stats from rendered leads only (lead_contexts),
        # not from the pre-filter `leads` list, so cover page stats match
        # the leads that actually appear in the PDF body.
        by_jurisdiction: dict[str, int] = {}
        for lctx in lead_contexts:
            j = lctx.get("jurisdiction") or "Unknown"
            by_jurisdiction[j] = by_jurisdiction.get(j, 0) + 1

        summary: dict[str, Any] = {
            "total_leads": len(lead_contexts),
            "incidents": sum(
                1 for lctx in lead_contexts if lctx.get("lead_type") == "incident"
            ),
            "policies": sum(
                1 for lctx in lead_contexts if lctx.get("lead_type") == "policy"
            ),
            "high_priority_count": sum(
                1
                for lctx in lead_contexts
                if lctx.get("severity") in ("high", "critical")
            ),
            "by_jurisdiction": by_jurisdiction,
        }

        # Deduplicate citations
        all_source_citations = list(dict.fromkeys(all_source_citations))
        seen_legal: set[str] = set()
        deduped_legal: list[dict[str, Any]] = []
        for lc in all_legal_citations:
            key = (lc.get("case_name", ""), lc.get("citation", ""))
            key_str = f"{key[0]}|{key[1]}"
            if key_str not in seen_legal:
                seen_legal.add(key_str)
                deduped_legal.append(lc)
        all_legal_citations = deduped_legal

        # Render HTML
        context = {
            "report_date": report_date,
            "report_period": f"Through {now.strftime('%B %d, %Y')}",
            "summary": summary,
            "leads": lead_contexts,
            "all_source_citations": all_source_citations or None,
            "all_legal_citations": all_legal_citations or None,
            "skipped_leads": skipped or None,
        }
        html = _render_pdf_html(context)

        # Render PDF via WeasyPrint
        import weasyprint

        def _blocked_url_fetcher(url: str, **kwargs: Any) -> dict[str, str]:
            """Disable external URL fetching to prevent SSRF via embedded resources."""
            return {"string": "", "mime_type": "text/plain"}

        try:
            pdf_bytes = weasyprint.HTML(
                string=html,
                url_fetcher=_blocked_url_fetcher,
            ).write_pdf()
        except Exception as exc:
            logger.exception(
                "weasyprint_pdf_rendering_failed",
                error=str(exc),
                lead_count=len(leads),
            )
            raise RuntimeError(
                "PDF rendering failed"
            ) from exc

        # Archive to MinIO
        artifact_uri = await _archive_pdf(pdf_bytes, now)
        if not artifact_uri:
            raise RuntimeError("PDF archival to MinIO failed; aborting report cycle")

        # Create Report record and flush to populate UUIDMixin-generated id
        report = Report(
            artifact_uri=artifact_uri,
            generated_at=now,
            lead_count=len(lead_contexts),
            plan_id=_CAL_PLAN_ID,
        )
        db.add(report)
        await db.flush()

        # Update lead statuses and link to report (only rendered leads)
        for lead in all_leads:
            if lead.id not in rendered_lead_ids:
                continue
            lead.reported_at = now
            lead.report_id = report.id
            if lead.status == "new":
                lead.status = "reviewing"
        await db.commit()

        logger.info(
            "prospecting_report_generated",
            lead_count=len(lead_contexts),
            artifact_uri=artifact_uri,
        )

        return ReportResult(
            pdf_bytes=pdf_bytes,
            lead_count=len(lead_contexts),
            artifact_uri=artifact_uri,
            report_date=report_date,
        )


_REPORT_BUCKET = "osint-reports"


async def _archive_pdf(pdf_bytes: bytes, timestamp: datetime) -> str:
    """Upload PDF to MinIO via threadpool and return the artifact URI."""
    date_path = timestamp.strftime("%Y/%m/%d")
    time_part = timestamp.strftime("%H%M%S")
    object_name = f"prospecting/{date_path}/report-{time_part}.pdf"

    try:
        uri = await asyncio.to_thread(
            upload_pdf_to_minio,
            pdf_bytes,
            object_name,
            bucket=_REPORT_BUCKET,
            retention_class="evidentiary",
        )
        return uri
    except Exception as exc:
        logger.warning("minio_upload_failed", error=str(exc))
        return ""
