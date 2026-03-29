"""Prospecting report generator — orchestrates lead selection, narrative
generation, citation verification, and PDF rendering."""

from __future__ import annotations

import asyncio
import importlib.resources
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import structlog
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from osint_core.config import settings
from osint_core.models.lead import Lead
from osint_core.services.pdf_export import upload_pdf_to_minio

logger = structlog.get_logger()

_CAL_PLAN_ID = "cal-prospecting"

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
    stmt = select(Lead).where(
        Lead.plan_id == _CAL_PLAN_ID,
        or_(
            Lead.status == "new",
            (Lead.status == "reviewing") & (Lead.last_updated_at > Lead.reported_at),
        ),
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _generate_narrative(lead: Lead) -> dict[str, str]:
    """Generate narrative sections for a lead via vLLM."""
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
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{settings.vllm_url}/v1/chat/completions",
                json={
                    "model": settings.llm_model,
                    "messages": [
                        {"role": "system", "content": _NARRATIVE_SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    "max_tokens": 1500,
                    "temperature": 0.2,
                },
            )
            resp.raise_for_status()
    except Exception as exc:
        logger.warning("narrative_generation_failed", lead_id=str(lead.id), error=str(exc))
        return _fallback_narrative(lead)

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        result: dict[str, str] = json.loads(content)
        return result
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        logger.warning("narrative_parse_failed", lead_id=str(lead.id), error=str(exc))
        return _fallback_narrative(lead)


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
    template = env.get_template("prospecting_report.html.j2")
    return template.render(**context)


class ProspectingReportGenerator:
    """Orchestrates the full prospecting report pipeline."""

    async def generate_report(self, db: AsyncSession) -> ReportResult | None:
        """Generate a prospecting report for all reportable leads.

        Returns None if no reportable leads exist.
        """
        leads = await _select_reportable_leads(db)
        if not leads:
            logger.info("prospecting_report_no_leads")
            return None

        now = datetime.now(UTC)
        ct_now = now.astimezone(ZoneInfo("America/Chicago"))
        tz_abbr = ct_now.strftime("%Z")  # CST or CDT depending on DST
        report_date = ct_now.strftime(f"%B %d, %Y — %I:%M %p {tz_abbr}")

        # Build lead contexts with narrative sections
        lead_contexts = []
        all_source_citations: list[str] = []
        # TODO(#137): Legal citation verification via CourtListener is deferred
        # to a follow-up PR once the CourtListener service is integrated.
        all_legal_citations: list[dict[str, Any]] = []

        for lead in leads:
            sections = await _generate_narrative(lead)

            # Source citations from lead metadata
            source_cites: list[str] = []
            if lead.citations:
                source_cites = lead.citations.get("sources", [])
                all_source_citations.extend(source_cites)

            lead_contexts.append({
                "lead_type": lead.lead_type,
                "title": lead.title,
                "summary": lead.summary,
                "constitutional_basis": lead.constitutional_basis or [],
                "jurisdiction": lead.jurisdiction,
                "institution": lead.institution,
                "severity": lead.severity,
                "confidence": lead.confidence,
                "sections": sections,
                "source_citations": source_cites,
                "legal_citations": [],
            })

        # Build summary stats
        by_jurisdiction: dict[str, int] = {}
        for lead in leads:
            j = lead.jurisdiction or "Unknown"
            by_jurisdiction[j] = by_jurisdiction.get(j, 0) + 1

        summary: dict[str, Any] = {
            "total_leads": len(leads),
            "incidents": sum(1 for ld in leads if ld.lead_type == "incident"),
            "policies": sum(1 for ld in leads if ld.lead_type == "policy"),
            "high_priority_count": sum(
                1 for ld in leads if ld.severity in ("high", "critical")
            ),
            "by_jurisdiction": by_jurisdiction,
        }

        # Render HTML
        context = {
            "report_date": report_date,
            "report_period": f"Through {now.strftime('%B %d, %Y')}",
            "summary": summary,
            "leads": lead_contexts,
            "all_source_citations": all_source_citations or None,
            "all_legal_citations": all_legal_citations or None,
        }
        html = _render_pdf_html(context)

        # Render PDF via WeasyPrint
        import weasyprint

        def _blocked_url_fetcher(url: str, **kwargs: Any) -> dict[str, str]:
            """Disable external URL fetching to prevent SSRF via embedded resources."""
            return {"string": "", "mime_type": "text/plain"}

        pdf_bytes = weasyprint.HTML(
            string=html,
            url_fetcher=_blocked_url_fetcher,
        ).write_pdf()

        # Archive to MinIO
        artifact_uri = await _archive_pdf(pdf_bytes, now)
        if not artifact_uri:
            raise RuntimeError("PDF archival to MinIO failed; aborting report cycle")

        # Update lead statuses only after successful archival
        for lead in leads:
            lead.reported_at = now
            if lead.status == "new":
                lead.status = "reviewing"
        await db.commit()

        logger.info(
            "prospecting_report_generated",
            lead_count=len(leads),
            artifact_uri=artifact_uri,
        )

        return ReportResult(
            pdf_bytes=pdf_bytes,
            lead_count=len(leads),
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
            upload_pdf_to_minio, pdf_bytes, object_name, bucket=_REPORT_BUCKET
        )
        return uri
    except Exception as exc:
        logger.warning("minio_upload_failed", error=str(exc))
        return ""
