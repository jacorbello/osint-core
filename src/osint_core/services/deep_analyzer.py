"""Deep constitutional analysis service.

Retrieves full policy documents from MinIO, extracts text, sends to LLM
for clause-level constitutional analysis, and matches precedent via
CourtListener. For incident leads, fetches article content and produces
a corroboration assessment.

Two-pass architecture for policy analysis:
  Pass 1 (Screening): Full-document scan to detect relevance, language,
      and flag specific sections for detailed review.
  Pass 2 (Targeted): Per-section provision analysis with exact quoting,
      constitutional basis identification, and source citation.
"""

from __future__ import annotations

import json
import logging
import re
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

_SCREENING_SYSTEM_PROMPT = (
    "You are a constitutional law clerk performing initial review of a policy "
    "document for The Center For American Liberty.\n\n"
    "Your task: determine whether this document contains provisions that restrict, "
    "burden, or implicate constitutional rights. Identify the document language "
    "and generate a clean descriptive title.\n\n"
    "If the document is purely administrative (compensation, IT policies, procurement, "
    "facilities management), set relevant to false.\n\n"
    "For each relevant section, provide a short reference string (e.g. '§ 4.2 - "
    "Pronoun Requirements') that identifies where in the document the issue appears.\n\n"
    "Respond with JSON:\n"
    '{"relevant": true, "language": "en", "lead_title": "Descriptive Title", '
    '"document_summary": "...", "overall_assessment": "...", '
    '"flagged_sections": ["§ 4.2 - Pronoun Requirements", "§ 5.1 - Protest Zones"]}\n\n'
    "language: ISO 639-1 code (en, es, tl, etc.)\n"
    "flagged_sections: list of section reference strings to review in detail. "
    "Empty list if not relevant."
)

_PROVISION_SYSTEM_PROMPT = (
    "You are a constitutional law clerk for The Center For American Liberty "
    "performing detailed analysis of a specific policy section.\n\n"
    "You MUST quote the EXACT language from the document — do not fabricate "
    "or paraphrase. If you cannot find exact text to quote, say so.\n\n"
    "Respond with JSON:\n"
    '{"section_reference": "§ X.Y", "quoted_language": "exact text from document", '
    '"constitutional_issue": "description of the issue", '
    '"constitutional_basis": "1A-free-speech", "severity": "high", '
    '"affected_population": "who is affected", '
    '"facial_or_as_applied": "facial", '
    '"sources_cited": ["Case Name v. Party"]}\n\n'
    "constitutional_basis must be one of: 1A-free-speech, 1A-religion, 1A-assembly, "
    "1A-press, 14A-due-process, 14A-equal-protection, parental-rights.\n"
    "severity must be one of: info, low, medium, high, critical.\n"
    "facial_or_as_applied must be one of: facial, as-applied, both.\n"
    "sources_cited: list of case names or legal authorities supporting the analysis."
)

# Regex for extracting section numbers from references
_SECTION_NUM_RE = re.compile(r"\d+(?:\.\d+)*")
_SECTION_MARKER_RE = re.compile(
    r"(?:§|Section|Article|Rule|PART)\s*(\d+(?:\.\d+)*)",
    re.IGNORECASE,
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
    # Policy analysis — two-pass architecture
    # ------------------------------------------------------------------

    async def _analyze_policy(self, lead: Any, event: Any) -> dict[str, Any] | None:
        metadata = event.metadata_ or {}
        minio_uri = metadata.get("minio_uri")

        # Step 1: Retrieve document (MinIO first, URL fallback)
        doc_bytes = None
        if minio_uri:
            doc_bytes = await self._retrieve_document(minio_uri)

        if not doc_bytes:
            # Fallback: fetch from source URL
            source_url = metadata.get("url") or metadata.get("tweet_url")
            if source_url:
                doc_bytes = await self._fetch_url_content(source_url)

        if not doc_bytes:
            logger.info(
                "deep_analysis_no_source",
                extra={"lead_id": str(lead.id), "reason": "no document available"},
            )
            return None

        # Step 2: Extract text
        doc_type = self._get_document_type(metadata, minio_uri or "")
        text = DocumentExtractor.extract(doc_bytes, doc_type)

        # Step 3: Quality gates
        if not text or not DocumentExtractor.check_content(text):
            logger.info("deep_analysis_no_content", extra={"lead_id": str(lead.id)})
            return {"analysis_status": "no_content", "actionable": False, "provisions": []}

        encoding_result = DocumentExtractor.validate_encoding(text)
        if not encoding_result.passed:
            logger.info(
                "deep_analysis_encoding_failed",
                extra={
                    "lead_id": str(lead.id),
                    "reason": encoding_result.failure_reason,
                },
            )
            return {
                "analysis_status": encoding_result.failure_reason or "extraction_failed",
                "actionable": False,
                "provisions": [],
            }

        detected_lang = DocumentExtractor.detect_language(text)
        if detected_lang not in ("en", "unknown"):
            logger.info(
                "deep_analysis_non_english",
                extra={"lead_id": str(lead.id), "language": detected_lang},
            )
            return {
                "analysis_status": "non_english",
                "language": detected_lang,
                "actionable": False,
                "provisions": [],
            }

        # Step 4: Pass 1 — Screening
        screening = await self._screen_document(lead, event, text)
        if screening is None:
            logger.warning("deep_analysis_screening_failed", extra={"lead_id": str(lead.id)})
            return None

        # Check screening language (LLM may detect language missed by langdetect)
        llm_lang = screening.get("language", "en")
        if llm_lang not in ("en", "unknown"):
            return {
                "analysis_status": "non_english",
                "language": llm_lang,
                "actionable": False,
                "provisions": [],
                "document_summary": screening.get("document_summary", ""),
                "lead_title": screening.get("lead_title", ""),
            }

        flagged = screening.get("flagged_sections", [])
        if not screening.get("relevant") or not flagged:
            return {
                "analysis_status": "not_actionable",
                "actionable": False,
                "provisions": [],
                "document_summary": screening.get("document_summary", ""),
                "overall_assessment": screening.get("overall_assessment", ""),
                "lead_title": screening.get("lead_title", ""),
            }

        # Step 5: Gather corroborating events
        corroborating = self._gather_corroborating_events(lead, event)

        # Step 6: Pass 2 — Targeted provision analysis
        provisions: list[dict[str, Any]] = []
        for section_ref in flagged:
            provision = await self._analyze_provision(
                lead, event,
                full_doc=text,
                flagged_section=section_ref,
                corroborating_events=corroborating,
            )
            if provision:
                provisions.append(provision)

        # Deduplicate by section_reference
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for p in provisions:
            ref = p.get("section_reference", "")
            if ref not in seen:
                seen.add(ref)
                unique.append(p)

        analysis: dict[str, Any] = {
            "provisions": unique,
            "document_summary": screening.get("document_summary", ""),
            "overall_assessment": screening.get("overall_assessment", ""),
            "lead_title": screening.get("lead_title", ""),
            "actionable": len(unique) > 0,
            "analysis_status": "complete" if unique else "not_actionable",
        }

        # Step 7: Attach precedent
        analysis = await self._attach_precedent(analysis)
        return analysis

    # ------------------------------------------------------------------
    # Pass 1: Screening
    # ------------------------------------------------------------------

    async def _screen_document(
        self, lead: Any, event: Any, doc_text: str,
    ) -> dict[str, Any] | None:
        """Send full document for relevance screening (Pass 1).

        Returns screening result dict with: relevant, language, lead_title,
        document_summary, overall_assessment, flagged_sections.
        Returns None if LLM call fails.
        """
        metadata = event.metadata_ or {}
        user_msg = (
            f"Institution: {lead.institution or 'Unknown'}\n"
            f"Jurisdiction: {lead.jurisdiction or 'Unknown'}\n"
            f"Scraper title: {lead.title or 'Unknown'}\n"
            f"Source URL: {metadata.get('url', 'N/A')}\n\n"
            f"--- FULL DOCUMENT TEXT ---\n\n"
            f"{doc_text[:25_000]}"
        )

        try:
            content = await llm_chat_completion(
                messages=[
                    {"role": "system", "content": _SCREENING_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=1500,
                temperature=0.1,
                timeout=60.0,
                response_format={"type": "json_object"},
            )
            return json.loads(content)
        except Exception as exc:
            logger.warning(
                "deep_analysis_screening_failed",
                extra={"lead_id": str(lead.id), "error": str(exc)},
            )
            return None

    # ------------------------------------------------------------------
    # Section text extraction
    # ------------------------------------------------------------------

    def _extract_section_text(
        self, full_text: str, section_ref: str, context_chars: int = 2000,
    ) -> str:
        """Extract section text from full document matching section_ref.

        Tries: (1) exact substring, (2) normalized number match,
        (3) fuzzy keyword match, (4) fallback to document start.
        """
        # Strategy 1: Exact substring match
        # Strip trailing description after dash for matching
        clean_ref = section_ref.split(" - ")[0].strip() if " - " in section_ref else section_ref
        idx = full_text.find(clean_ref)
        if idx >= 0:
            start = max(0, idx - 200)
            end = min(len(full_text), idx + context_chars)
            return full_text[start:end]

        # Strategy 2: Normalized number match
        nums = _SECTION_NUM_RE.findall(section_ref)
        if nums:
            for num in nums:
                pattern = re.compile(
                    rf"(?:§|Section|Article|Rule|PART)\s*{re.escape(num)}",
                    re.IGNORECASE,
                )
                match = pattern.search(full_text)
                if match:
                    start = max(0, match.start() - 200)
                    end = min(len(full_text), match.start() + context_chars)
                    return full_text[start:end]

        # Strategy 3: Fuzzy — search for significant words from section_ref
        stop_words = {"the", "a", "an", "of", "in", "for", "and", "or", "to", "is", "at", "by"}
        words = [
            w for w in re.findall(r"[a-zA-Z]+", section_ref)
            if len(w) > 2 and w.lower() not in stop_words
        ]
        if words:
            # Search for any significant word
            for word in words:
                pattern = re.compile(re.escape(word), re.IGNORECASE)
                match = pattern.search(full_text)
                if match:
                    start = max(0, match.start() - 200)
                    end = min(len(full_text), match.start() + context_chars)
                    return full_text[start:end]

        # Strategy 4: Fallback — return start of document
        return full_text[:context_chars]

    # ------------------------------------------------------------------
    # Pass 2: Targeted provision analysis
    # ------------------------------------------------------------------

    async def _analyze_provision(
        self,
        lead: Any,
        event: Any,
        full_doc: str,
        flagged_section: str,
        *,
        corroborating_events: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Analyze a single flagged section in detail (Pass 2).

        Returns provision dict or None if LLM call fails.
        """
        metadata = event.metadata_ or {}
        section_text = self._extract_section_text(full_doc, flagged_section)

        # Build precedent context
        precedent_context = ""
        precedent_cases = self._get_precedent_for_basis(flagged_section)
        if precedent_cases:
            case_lines = [f"  - {c.get('case', '')} ({c.get('citation', '')})" for c in precedent_cases]
            precedent_context = "\nRelevant precedent:\n" + "\n".join(case_lines) + "\n"

        # Build corroboration context
        corroboration_context = ""
        if corroborating_events:
            event_lines = []
            for ce in corroborating_events[:5]:
                event_lines.append(f"  - {ce.get('title', 'N/A')}: {ce.get('summary', 'N/A')}")
            corroboration_context = "\nCorroborating events:\n" + "\n".join(event_lines) + "\n"

        user_msg = (
            f"Source: {lead.institution or 'Unknown'} ({lead.jurisdiction or 'Unknown'})\n"
            f"Document: {lead.title or 'Unknown'}\n"
            f"URL: {metadata.get('url', 'N/A')}\n"
            f"Flagged section: {flagged_section}\n"
            f"{precedent_context}"
            f"{corroboration_context}"
            f"\n--- SECTION TEXT WITH CONTEXT ---\n\n"
            f"{section_text}"
        )

        try:
            content = await llm_chat_completion(
                messages=[
                    {"role": "system", "content": _PROVISION_SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                max_tokens=1500,
                temperature=0.1,
                timeout=60.0,
                response_format={"type": "json_object"},
            )
            return json.loads(content)
        except Exception as exc:
            logger.warning(
                "deep_analysis_provision_failed",
                extra={
                    "lead_id": str(lead.id),
                    "section": flagged_section,
                    "error": str(exc),
                },
            )
            return None

    # ------------------------------------------------------------------
    # Precedent helpers
    # ------------------------------------------------------------------

    def _get_precedent_for_basis(self, constitutional_basis: str) -> list[dict[str, str]]:
        """Get up to 3 cases from precedent_map matching the basis."""
        basis_map = self._precedent_map.get(constitutional_basis, {})
        cases: list[dict[str, str]] = []
        for _issue, case_list in basis_map.items():
            for case in case_list:
                if case not in cases:
                    cases.append(case)
                if len(cases) >= 3:
                    return cases
        return cases

    # ------------------------------------------------------------------
    # Corroborating events
    # ------------------------------------------------------------------

    def _gather_corroborating_events(
        self, lead: Any, event: Any,
    ) -> list[dict[str, Any]]:
        """Build corroborating event summary from primary event.

        Full multi-event DB query comes in Task 8; for now, use the
        primary event as a single corroborating data point.
        """
        result: list[dict[str, Any]] = []
        title = getattr(event, "title", None) or ""
        summary = getattr(event, "nlp_summary", None) or getattr(event, "summary", None) or ""
        source = getattr(event, "source_id", None) or ""

        if title or summary:
            result.append({
                "title": title,
                "summary": summary,
                "source": source,
            })
        return result

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

    async def _fetch_url_content(self, url: str) -> bytes | None:
        """Fetch document content from a URL as fallback when MinIO fails."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, follow_redirects=True)
                resp.raise_for_status()
                return resp.content
        except Exception as exc:
            logger.warning(
                "deep_analysis_url_fetch_failed",
                extra={"url": url, "error": str(exc)},
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
