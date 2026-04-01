"""Deep constitutional analysis service.

Retrieves full policy documents from MinIO, extracts text, sends to LLM
for clause-level constitutional analysis, and matches precedent via
CourtListener. For incident leads, fetches article content and produces
a corroboration assessment.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from minio import Minio

from osint_core.config import settings
from osint_core.llm import llm_chat_completion
from osint_core.services.courtlistener import CourtListenerClient
from osint_core.services.document_extractor import DocumentExtractor

logger = logging.getLogger(__name__)

_POLICY_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "provisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "section_reference": {"type": "string"},
                    "quoted_language": {"type": "string"},
                    "constitutional_issue": {"type": "string"},
                    "constitutional_basis": {
                        "enum": [
                            "1A-free-speech", "1A-religion", "1A-assembly", "1A-press",
                            "14A-due-process", "14A-equal-protection", "parental-rights",
                        ]
                    },
                    "severity": {"enum": ["info", "low", "medium", "high", "critical"]},
                    "affected_population": {"type": "string"},
                    "facial_or_as_applied": {"enum": ["facial", "as-applied", "both"]},
                },
                "required": [
                    "section_reference", "quoted_language", "constitutional_issue",
                    "constitutional_basis", "severity", "affected_population",
                    "facial_or_as_applied",
                ],
                "additionalProperties": False,
            },
        },
        "document_summary": {"type": "string"},
        "overall_assessment": {"type": "string"},
        "actionable": {"type": "boolean"},
    },
    "required": ["provisions", "document_summary", "overall_assessment", "actionable"],
    "additionalProperties": False,
}

_INCIDENT_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "incident_summary": {"type": "string"},
        "rights_violated": {
            "type": "array",
            "items": {
                "enum": [
                    "1A-free-speech", "1A-religion", "1A-assembly", "1A-press",
                    "14A-due-process", "14A-equal-protection", "parental-rights",
                ]
            },
        },
        "individuals_identified": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "role": {"type": "string"},
                },
                "required": ["name", "role"],
                "additionalProperties": False,
            },
        },
        "institution": {"type": "string"},
        "corroboration_strength": {"enum": ["strong", "moderate", "weak", "unverified"]},
        "corroboration_notes": {"type": "string"},
        "actionable": {"type": "boolean"},
    },
    "required": [
        "incident_summary", "rights_violated", "individuals_identified",
        "institution", "corroboration_strength", "corroboration_notes", "actionable",
    ],
    "additionalProperties": False,
}

_POLICY_SYSTEM_PROMPT = (
    "You are a constitutional law clerk reviewing a policy document for "
    "The Center For American Liberty. Your job is to identify specific provisions "
    "that restrict, burden, or implicate constitutional rights.\n\n"
    "For each problematic provision:\n"
    "1. Quote the EXACT language from the document\n"
    "2. Cite the section/rule number\n"
    "3. Explain which constitutional right is affected and how\n"
    "4. Assess severity (info/low/medium/high/critical)\n"
    "5. Identify the affected population\n"
    "6. Determine if this is a facial challenge or as-applied\n\n"
    "If the document contains NO constitutional issues, return an empty provisions "
    "array and set actionable to false. Do not stretch to find issues that aren't there.\n\n"
    "CRITICAL: Only quote language that actually appears in the document. "
    "Do not fabricate or paraphrase policy text.\n\n"
    "Respond with JSON in this exact structure:\n"
    '{"provisions": [{"section_reference": "...", "quoted_language": "...", '
    '"constitutional_issue": "...", "constitutional_basis": "1A-free-speech", '
    '"severity": "high", "affected_population": "...", '
    '"facial_or_as_applied": "facial"}], '
    '"document_summary": "...", "overall_assessment": "...", "actionable": true}\n\n'
    "constitutional_basis must be one of: 1A-free-speech, 1A-religion, 1A-assembly, "
    "1A-press, 14A-due-process, 14A-equal-protection, parental-rights.\n"
    "severity must be one of: info, low, medium, high, critical.\n"
    "facial_or_as_applied must be one of: facial, as-applied, both."
)

_INCIDENT_SYSTEM_PROMPT = (
    "You are a constitutional rights analyst for The Center For American Liberty. "
    "Assess this incident report for litigation potential.\n\n"
    "Identify: who was harmed, what right was violated, which institution is responsible, "
    "and how strong the corroboration is.\n\n"
    "Corroboration strength:\n"
    "- strong: multiple independent sources, named individuals, official statements\n"
    "- moderate: 2+ sources or one credible detailed report\n"
    "- weak: single source, anonymous, or vague details\n"
    "- unverified: social media only, no corroboration\n\n"
    "If the incident does not involve constitutional rights, set actionable to false.\n\n"
    "Respond with JSON in this exact structure:\n"
    '{"incident_summary": "...", "rights_violated": ["1A-free-speech"], '
    '"individuals_identified": [{"name": "...", "role": "..."}], '
    '"institution": "...", "corroboration_strength": "strong", '
    '"corroboration_notes": "...", "actionable": true}'
)


class DeepAnalyzer:
    """Orchestrates deep constitutional analysis of leads."""

    def __init__(
        self,
        *,
        precedent_map: dict[str, dict[str, list[dict[str, str]]]],
        courtlistener: CourtListenerClient | None = None,
    ) -> None:
        self._precedent_map = precedent_map
        self._courtlistener = courtlistener or CourtListenerClient()

    async def analyze_lead(self, lead: Any, event: Any) -> dict[str, Any] | None:
        """Run deep analysis on a lead using its source event's document.

        Returns the analysis dict, or None if no source material is available.

        The analysis path is determined by the **source type**, not
        ``lead.lead_type``, because NLP triage frequently misclassifies
        university policy documents as incidents.  If the source event
        came from a ``university_policy`` connector or has a ``minio_uri``
        in its metadata, the policy analysis path is used regardless of
        the lead type classification.
        """
        metadata = event.metadata_ or {}
        source_id: str = getattr(event, "source_id", "") or ""
        has_archived_doc = bool(metadata.get("minio_uri"))
        is_policy_source = source_id.startswith("univ_")

        if has_archived_doc or is_policy_source:
            return await self._analyze_policy(lead, event)
        return await self._analyze_incident(lead, event)

    # ------------------------------------------------------------------
    # Policy analysis
    # ------------------------------------------------------------------

    async def _analyze_policy(self, lead: Any, event: Any) -> dict[str, Any] | None:
        metadata = event.metadata_ or {}
        minio_uri = metadata.get("minio_uri")

        if not minio_uri:
            logger.info(
                "deep_analysis_no_source",
                extra={"lead_id": str(lead.id), "reason": "no minio_uri"},
            )
            return None

        doc_bytes = await self._retrieve_document(minio_uri)
        if not doc_bytes:
            return None

        doc_type = self._get_document_type(metadata, minio_uri)
        text = DocumentExtractor.extract(doc_bytes, doc_type)

        if not text or not text.strip():
            logger.info("deep_analysis_empty_document", extra={"lead_id": str(lead.id)})
            return None

        chunks = DocumentExtractor.chunk(
            text,
            document_title=lead.title or "",
            institution=lead.institution or "",
        )

        all_provisions: list[dict[str, Any]] = []
        doc_summary = ""
        overall = ""
        actionable = False

        for chunk in chunks:
            user_msg = (
                f"Institution: {lead.institution or 'Unknown'}\n"
                f"Jurisdiction: {lead.jurisdiction or 'Unknown'}\n"
                f"Document title: {lead.title or 'Unknown'}\n\n"
                f"--- DOCUMENT TEXT (chunk {chunk.index + 1}/{chunk.total}) ---\n\n"
                f"{chunk.text}"
            )

            try:
                content = await llm_chat_completion(
                    messages=[
                        {"role": "system", "content": _POLICY_SYSTEM_PROMPT},
                        {"role": "user", "content": user_msg},
                    ],
                    max_tokens=2000,
                    temperature=0.1,
                    timeout=60.0,
                    response_format={"type": "json_object"},
                )
                result = json.loads(content)
            except Exception as exc:
                logger.warning(
                    "deep_analysis_llm_failed",
                    extra={"lead_id": str(lead.id), "chunk": chunk.index, "error": str(exc)},
                )
                continue

            all_provisions.extend(result.get("provisions", []))
            if not doc_summary:
                doc_summary = result.get("document_summary", "")
            if not overall:
                overall = result.get("overall_assessment", "")
            if result.get("actionable"):
                actionable = True

        # Deduplicate provisions by section_reference
        seen_sections: set[str] = set()
        unique_provisions: list[dict[str, Any]] = []
        for p in all_provisions:
            ref = p.get("section_reference", "")
            if ref not in seen_sections:
                seen_sections.add(ref)
                unique_provisions.append(p)

        analysis: dict[str, Any] = {
            "provisions": unique_provisions,
            "document_summary": doc_summary,
            "overall_assessment": overall,
            "actionable": actionable,
        }

        # Attach precedent to each provision
        analysis = await self._attach_precedent(analysis)
        return analysis

    # ------------------------------------------------------------------
    # Incident analysis
    # ------------------------------------------------------------------

    async def _analyze_incident(self, lead: Any, event: Any) -> dict[str, Any] | None:
        content_text = await self._fetch_article_content(event)

        if not content_text:
            logger.info(
                "deep_analysis_no_source",
                extra={"lead_id": str(lead.id), "reason": "no article content"},
            )
            return None

        user_msg = (
            f"Institution: {lead.institution or 'Unknown'}\n"
            f"Jurisdiction: {lead.jurisdiction or 'Unknown'}\n\n"
            f"--- SOURCE MATERIAL ---\n\n{content_text[:100_000]}"
        )

        try:
            response = await llm_chat_completion(
                messages=[
                    {"role": "system", "content": _INCIDENT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=1500,
                temperature=0.1,
                timeout=30.0,
                response_format={"type": "json_object"},
            )
            result: dict[str, Any] = json.loads(response)
            return result
        except Exception as exc:
            logger.warning(
                "deep_analysis_llm_failed",
                extra={"lead_id": str(lead.id), "error": str(exc)},
            )
            return None

    # ------------------------------------------------------------------
    # Precedent attachment
    # ------------------------------------------------------------------

    async def _attach_precedent(self, analysis: dict[str, Any]) -> dict[str, Any]:
        """For each provision, look up and verify relevant precedent."""
        for provision in analysis.get("provisions", []):
            basis = provision.get("constitutional_basis", "")
            issue = provision.get("constitutional_issue", "")

            citations = await self._courtlistener.lookup_precedent(
                constitutional_basis=basis,
                constitutional_issue=issue,
                precedent_map=self._precedent_map,
            )

            provision["precedent"] = [
                {
                    "case_name": c.case_name,
                    "citation": c.citation,
                    "courtlistener_url": c.courtlistener_url,
                    "verified": c.verified,
                    "holding_summary": c.holding_summary,
                }
                for c in citations
            ]

        return analysis

    # ------------------------------------------------------------------
    # Document retrieval helpers
    # ------------------------------------------------------------------

    async def _retrieve_document(self, minio_uri: str) -> bytes | None:
        """Download a document from MinIO by its URI."""
        # Parse minio://bucket/key
        if not minio_uri.startswith("minio://"):
            return None

        path = minio_uri[len("minio://"):]
        slash = path.index("/")
        bucket = path[:slash]
        key = path[slash + 1:]

        try:
            client = Minio(
                settings.minio_endpoint,
                settings.minio_access_key,
                settings.minio_secret_key,
                secure=settings.minio_secure,
            )
            response = client.get_object(bucket, key)
            data = response.read()
            response.close()
            response.release_conn()
            return data
        except Exception as exc:
            logger.warning(
                "deep_analysis_minio_failed",
                extra={"uri": minio_uri, "error": str(exc)},
            )
            return None

    @staticmethod
    def _get_document_type(metadata: dict[str, Any], minio_uri: str) -> str:
        """Determine document type from metadata or URI."""
        doc_type: str = metadata.get("document_type", "")
        if doc_type in ("pdf", "html"):
            return doc_type
        if minio_uri.lower().endswith(".pdf"):
            return "pdf"
        return "html"

    async def _fetch_article_content(self, event: Any) -> str | None:
        """Fetch article content for incident leads."""
        metadata = event.metadata_ or {}
        url = metadata.get("url") or metadata.get("tweet_url")

        if not url and event.raw_excerpt:
            candidate = event.raw_excerpt.strip()
            if candidate.startswith(("http://", "https://")):
                url = candidate

        if not url:
            # Use NLP summary as fallback content
            summary = getattr(event, "nlp_summary", None) or getattr(event, "summary", None)
            return summary

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(url, follow_redirects=True)
                resp.raise_for_status()
                return DocumentExtractor.extract_html(resp.text)
        except Exception as exc:
            logger.warning("deep_analysis_fetch_failed", extra={"url": url, "error": str(exc)})
            # Fall back to summary
            return getattr(event, "nlp_summary", None) or getattr(event, "summary", None)
