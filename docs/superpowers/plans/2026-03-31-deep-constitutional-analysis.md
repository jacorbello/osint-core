# Deep Constitutional Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a deep analysis pipeline stage that reads full policy documents from MinIO, identifies specific constitutional provisions with quoted language, verifies precedent via CourtListener, and produces clause-level report output.

**Architecture:** New `DocumentExtractor` service extracts text from HTML/PDF and chunks large documents. New `DeepAnalyzer` service orchestrates LLM analysis + CourtListener precedent lookup per lead. New Celery task `analyze_leads` runs after `match_leads` and before report generation. Report generator renders deep analysis provisions directly instead of calling the narrative LLM.

**Tech Stack:** Python 3.12, SQLAlchemy (async), Celery, Groq API (gpt-oss-20b, strict structured output), PyMuPDF (fitz), BeautifulSoup4, CourtListener REST API, MinIO, Alembic, pytest

---

## File Structure

| File | Responsibility |
|------|---------------|
| `src/osint_core/services/document_extractor.py` (new) | Extract text from HTML/PDF, chunk large documents with overlap |
| `src/osint_core/services/deep_analyzer.py` (new) | Orchestrate deep analysis: retrieve doc, extract text, call LLM, match precedent, store results |
| `migrations/versions/0010_add_deep_analysis.py` (new) | Add `deep_analysis` JSONB + `analysis_status` columns to leads table |
| `src/osint_core/models/lead.py` (modify) | Add new columns |
| `src/osint_core/workers/prospecting.py` (modify) | Add `analyze_leads_task`, wire into pipeline |
| `src/osint_core/services/prospecting_report.py` (modify) | Render deep analysis provisions when available |
| `src/osint_core/templates/prospecting_report.html` (modify) | New template sections for clause-level findings |
| `src/osint_core/services/courtlistener.py` (modify) | Add `lookup_precedent()` for precedent map matching |
| `plans/cal-prospecting.yaml` (modify) | Add `precedent_map`, `deep_analysis_enabled`, `deep_analysis_relevance_gate` |
| `tests/test_document_extractor.py` (new) | Tests for text extraction and chunking |
| `tests/test_deep_analyzer.py` (new) | Tests for deep analysis orchestration |
| `tests/test_deep_analysis_integration.py` (new) | Tests for pipeline wiring and report rendering |

---

### Task 1: Alembic Migration — Add deep_analysis columns to leads

**Files:**
- Create: `migrations/versions/0010_add_deep_analysis.py`

- [ ] **Step 1: Create migration file**

```python
"""add deep_analysis and analysis_status to leads

Revision ID: 0010
Revises: 0009
Create Date: 2026-03-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = None if context.is_offline_mode() else op.get_bind()

    op.add_column(
        "leads",
        sa.Column("deep_analysis", postgresql.JSONB(), nullable=True),
        schema="osint",
    )
    op.add_column(
        "leads",
        sa.Column(
            "analysis_status",
            sa.Text(),
            nullable=False,
            server_default="pending",
        ),
        schema="osint",
    )
    op.create_check_constraint(
        op.f("ck_leads_analysis_status_valid"),
        "leads",
        "analysis_status IN ('pending', 'completed', 'no_source_material', 'failed')",
        schema="osint",
    )
    op.create_index(
        "ix_leads_analysis_status",
        "leads",
        ["analysis_status"],
        schema="osint",
    )


def downgrade() -> None:
    op.drop_index("ix_leads_analysis_status", table_name="leads", schema="osint")
    op.drop_constraint(
        op.f("ck_leads_analysis_status_valid"), "leads", schema="osint"
    )
    op.drop_column("leads", "analysis_status", schema="osint")
    op.drop_column("leads", "deep_analysis", schema="osint")
```

- [ ] **Step 2: Verify migration applies**

Run: `cd /root/repos/personal/osint-core && alembic upgrade head --sql | tail -20`
Expected: SQL output showing `ALTER TABLE osint.leads ADD COLUMN deep_analysis JSONB` and `ADD COLUMN analysis_status TEXT`.

- [ ] **Step 3: Commit**

```bash
git add migrations/versions/0010_add_deep_analysis.py
git commit -m "feat: add deep_analysis and analysis_status columns to leads table"
```

---

### Task 2: Update Lead Model

**Files:**
- Modify: `src/osint_core/models/lead.py`

- [ ] **Step 1: Add new columns to Lead model**

Add these two columns after the `citations` column (around line 60):

```python
    deep_analysis: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, default=None
    )
    analysis_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="pending"
    )
```

Add a CheckConstraint to `__table_args__` (in the existing tuple, before the closing parenthesis):

```python
        CheckConstraint(
            "analysis_status IN ('pending', 'completed', 'no_source_material', 'failed')",
            name="ck_leads_analysis_status_valid",
        ),
```

Add an index to `__table_args__`:

```python
        Index("ix_leads_analysis_status", "analysis_status"),
```

- [ ] **Step 2: Verify model loads**

Run: `python3 -c "from osint_core.models.lead import Lead; print(Lead.__table__.columns.keys())"`
Expected: Output includes `deep_analysis` and `analysis_status`.

- [ ] **Step 3: Commit**

```bash
git add src/osint_core/models/lead.py
git commit -m "feat: add deep_analysis and analysis_status to Lead model"
```

---

### Task 3: DocumentExtractor Service

**Files:**
- Create: `src/osint_core/services/document_extractor.py`
- Create: `tests/test_document_extractor.py`

- [ ] **Step 1: Write tests**

```python
"""Tests for DocumentExtractor service."""

from __future__ import annotations

import pytest

from osint_core.services.document_extractor import DocumentExtractor, DocumentChunk


class TestExtractHtml:
    def test_extracts_text_with_headings(self) -> None:
        html = "<h1>Title</h1><p>Body text here.</p><h2>Section 2</h2><p>More text.</p>"
        result = DocumentExtractor.extract_html(html)
        assert "# Title" in result
        assert "## Section 2" in result
        assert "Body text here." in result

    def test_strips_scripts_and_styles(self) -> None:
        html = "<style>body{}</style><script>alert(1)</script><p>Real content</p>"
        result = DocumentExtractor.extract_html(html)
        assert "alert" not in result
        assert "body{}" not in result
        assert "Real content" in result

    def test_empty_html(self) -> None:
        assert DocumentExtractor.extract_html("") == ""


class TestExtractPdf:
    def test_extract_from_bytes(self) -> None:
        # Minimal valid PDF
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Test PDF content on page 1")
        pdf_bytes = doc.tobytes()
        doc.close()

        result = DocumentExtractor.extract_pdf(pdf_bytes)
        assert "Test PDF content on page 1" in result
        assert "[Page 1]" in result

    def test_empty_pdf(self) -> None:
        import fitz
        doc = fitz.open()
        doc.new_page()  # blank page
        pdf_bytes = doc.tobytes()
        doc.close()
        result = DocumentExtractor.extract_pdf(pdf_bytes)
        assert "[Page 1]" in result


class TestChunking:
    def test_small_document_single_chunk(self) -> None:
        text = "Short document. " * 100
        chunks = DocumentExtractor.chunk(text, max_chars=300_000)
        assert len(chunks) == 1
        assert chunks[0].text == text
        assert chunks[0].index == 0
        assert chunks[0].total == 1

    def test_large_document_splits(self) -> None:
        # Build a document with clear section boundaries
        sections = []
        for i in range(10):
            sections.append(f"## Section {i}\n{'Content. ' * 500}")
        text = "\n\n".join(sections)
        chunks = DocumentExtractor.chunk(text, max_chars=2000)
        assert len(chunks) > 1
        # Each chunk should have the preamble context
        for chunk in chunks:
            assert chunk.total == len(chunks)

    def test_overlap_preserves_context(self) -> None:
        sections = [f"## Section {i}\nParagraph {i} content." for i in range(5)]
        text = "\n\n".join(sections)
        chunks = DocumentExtractor.chunk(text, max_chars=100, overlap_chars=30)
        # Overlapping chunks should share some text
        if len(chunks) >= 2:
            # The end of chunk 0 should overlap with start of chunk 1
            assert len(chunks[0].text) > 0
            assert len(chunks[1].text) > 0

    def test_toc_extraction(self) -> None:
        text = "# Main Title\nIntro.\n## Section A\nContent A.\n## Section B\nContent B."
        toc = DocumentExtractor.extract_toc(text)
        assert "Main Title" in toc
        assert "Section A" in toc
        assert "Section B" in toc
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_document_extractor.py -v`
Expected: ImportError — module does not exist yet.

- [ ] **Step 3: Implement DocumentExtractor**

```python
"""Document text extraction and chunking for deep analysis.

Extracts readable text from HTML (preserving section structure) and PDF
(preserving page markers). Chunks large documents with configurable overlap
and section-boundary-aware splitting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

# Heading tags → markdown heading levels
_HEADING_MAP = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}

# Default chunking thresholds (characters, not tokens)
DEFAULT_MAX_CHARS = 300_000  # ~80k tokens
DEFAULT_OVERLAP_CHARS = 20_000  # ~5k tokens

# Section boundary patterns for splitting
_SECTION_RE = re.compile(
    r"(?:^|\n)(?=(?:#{1,6}\s|§\s*\d|Article\s+\d|Section\s+\d|Rule\s+\d|PART\s+\d))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DocumentChunk:
    """A chunk of document text with position metadata."""

    text: str
    index: int
    total: int
    toc: str = ""


class DocumentExtractor:
    """Extracts text from HTML/PDF and chunks large documents."""

    @staticmethod
    def extract_html(html: str) -> str:
        """Extract text from HTML, converting headings to markdown markers."""
        if not html or not html.strip():
            return ""

        soup = BeautifulSoup(html, "html.parser")

        # Remove non-content elements
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        # Convert headings to markdown markers
        for tag_name, prefix in _HEADING_MAP.items():
            for tag in soup.find_all(tag_name):
                text = tag.get_text(strip=True)
                tag.replace_with(f"\n\n{prefix} {text}\n\n")

        text = soup.get_text(separator="\n", strip=True)
        # Collapse excessive blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def extract_pdf(pdf_bytes: bytes) -> str:
        """Extract text from PDF bytes, preserving page markers."""
        import fitz  # PyMuPDF

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages: list[str] = []
        for i, page in enumerate(doc, start=1):
            text = page.get_text().strip()
            pages.append(f"[Page {i}]\n{text}")
        doc.close()
        return "\n\n".join(pages)

    @staticmethod
    def extract_toc(text: str) -> str:
        """Extract a table of contents from markdown-style headings."""
        lines: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                # Count heading level
                level = len(stripped) - len(stripped.lstrip("#"))
                title = stripped.lstrip("#").strip()
                indent = "  " * (level - 1)
                lines.append(f"{indent}- {title}")
        return "\n".join(lines)

    @staticmethod
    def chunk(
        text: str,
        *,
        max_chars: int = DEFAULT_MAX_CHARS,
        overlap_chars: int = DEFAULT_OVERLAP_CHARS,
        document_title: str = "",
        institution: str = "",
    ) -> list[DocumentChunk]:
        """Split text into chunks, preferring section boundaries.

        Documents under *max_chars* are returned as a single chunk.
        """
        if len(text) <= max_chars:
            return [DocumentChunk(text=text, index=0, total=1)]

        toc = DocumentExtractor.extract_toc(text)
        preamble = ""
        if document_title or institution:
            parts = [p for p in [document_title, institution] if p]
            preamble = f"Document: {' — '.join(parts)}\n"
        if toc:
            preamble += f"Table of Contents:\n{toc}\n\n---\n\n"

        # Find section boundaries
        boundaries = [m.start() for m in _SECTION_RE.finditer(text)]
        if not boundaries or boundaries[0] != 0:
            boundaries.insert(0, 0)

        content_max = max_chars - len(preamble)
        chunks: list[DocumentChunk] = []
        start = 0

        while start < len(text):
            end = start + content_max

            if end >= len(text):
                chunk_text = text[start:]
            else:
                # Find the nearest section boundary before end
                best = end
                for b in boundaries:
                    if start < b <= end:
                        best = b
                # If no boundary found in range, try paragraph break
                if best == end:
                    newline_pos = text.rfind("\n\n", start, end)
                    if newline_pos > start:
                        best = newline_pos
                chunk_text = text[start:best]

            full_text = preamble + chunk_text if preamble else chunk_text
            chunks.append(DocumentChunk(text=full_text, index=len(chunks), total=0, toc=toc))

            # Advance with overlap
            start += len(chunk_text)
            if start < len(text):
                start = max(start - overlap_chars, start - len(chunk_text) + 1)
                # Ensure forward progress
                if start <= chunks[-1].index:
                    start = chunks[-1].index + len(chunk_text)

        # Fix total count
        total = len(chunks)
        chunks = [
            DocumentChunk(text=c.text, index=c.index, total=total, toc=c.toc)
            for c in chunks
        ]
        return chunks

    @staticmethod
    def detect_type(content_bytes: bytes, content_type: str = "", url: str = "") -> str:
        """Detect whether content is PDF or HTML."""
        if "application/pdf" in content_type or url.lower().endswith(".pdf"):
            return "pdf"
        if content_bytes[:5] == b"%PDF-":
            return "pdf"
        return "html"

    @staticmethod
    def extract(content_bytes: bytes, doc_type: str) -> str:
        """Extract text from content bytes based on document type."""
        if doc_type == "pdf":
            return DocumentExtractor.extract_pdf(content_bytes)
        return DocumentExtractor.extract_html(content_bytes.decode("utf-8", errors="replace"))
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_document_extractor.py -v`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/osint_core/services/document_extractor.py tests/test_document_extractor.py
git commit -m "feat: add DocumentExtractor service for text extraction and chunking"
```

---

### Task 4: Add PyMuPDF dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add PyMuPDF to dependencies**

Add `PyMuPDF` to the `dependencies` list in `pyproject.toml`:

```
"PyMuPDF>=1.24.0",
```

- [ ] **Step 2: Install and verify**

Run: `pip install PyMuPDF && python3 -c "import fitz; print(fitz.__version__)"`
Expected: Version number prints.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add PyMuPDF dependency for PDF text extraction"
```

---

### Task 5: CourtListener Precedent Lookup

**Files:**
- Modify: `src/osint_core/services/courtlistener.py`
- Create: `tests/test_courtlistener_precedent.py`

- [ ] **Step 1: Write tests**

```python
"""Tests for CourtListener precedent lookup."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from osint_core.services.courtlistener import CourtListenerClient, VerifiedCitation


SAMPLE_PRECEDENT_MAP = {
    "1A-free-speech": {
        "compelled_speech": [
            {"case": "West Virginia v. Barnette", "citation": "319 U.S. 624 (1943)"},
            {"case": "303 Creative LLC v. Elenis", "citation": "600 U.S. 570 (2023)"},
        ],
        "speech_codes": [
            {"case": "Tinker v. Des Moines", "citation": "393 U.S. 503 (1969)"},
        ],
    },
    "14A-due-process": {
        "campus_discipline": [
            {"case": "Goss v. Lopez", "citation": "419 U.S. 565 (1975)"},
        ],
    },
}


class TestMatchPrecedent:
    def test_matches_compelled_speech(self) -> None:
        client = CourtListenerClient()
        matches = client.match_precedent(
            constitutional_basis="1A-free-speech",
            constitutional_issue="Compelled speech — requires students to affirm beliefs",
            precedent_map=SAMPLE_PRECEDENT_MAP,
        )
        assert len(matches) == 2
        assert matches[0]["case"] == "West Virginia v. Barnette"

    def test_matches_speech_codes(self) -> None:
        client = CourtListenerClient()
        matches = client.match_precedent(
            constitutional_basis="1A-free-speech",
            constitutional_issue="Speech code restricting campus expression",
            precedent_map=SAMPLE_PRECEDENT_MAP,
        )
        assert len(matches) >= 1
        assert any("Tinker" in m["case"] for m in matches)

    def test_no_match_returns_empty(self) -> None:
        client = CourtListenerClient()
        matches = client.match_precedent(
            constitutional_basis="parental-rights",
            constitutional_issue="Parental notification bypass",
            precedent_map=SAMPLE_PRECEDENT_MAP,
        )
        assert matches == []

    def test_unknown_basis_returns_empty(self) -> None:
        client = CourtListenerClient()
        matches = client.match_precedent(
            constitutional_basis="unknown-basis",
            constitutional_issue="Something",
            precedent_map=SAMPLE_PRECEDENT_MAP,
        )
        assert matches == []


class TestLookupPrecedent:
    @pytest.mark.asyncio
    async def test_verifies_matched_cases(self) -> None:
        client = CourtListenerClient()
        verified = VerifiedCitation(
            case_name="West Virginia v. Barnette",
            citation="319 U.S. 624 (1943)",
            courtlistener_url="https://www.courtlistener.com/opinion/123/",
            verified=True,
            holding_summary="Government cannot compel speech.",
        )
        with patch.object(client, "verify_citations", new_callable=AsyncMock, return_value=[verified]):
            results = await client.lookup_precedent(
                constitutional_basis="1A-free-speech",
                constitutional_issue="Compelled speech requirement",
                precedent_map=SAMPLE_PRECEDENT_MAP,
            )
        assert len(results) >= 1
        assert results[0].verified is True
        assert "Barnette" in results[0].case_name
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_courtlistener_precedent.py -v`
Expected: AttributeError — `match_precedent` and `lookup_precedent` don't exist yet.

- [ ] **Step 3: Add match_precedent and lookup_precedent to CourtListenerClient**

Add these methods to the `CourtListenerClient` class in `src/osint_core/services/courtlistener.py`:

```python
    def match_precedent(
        self,
        constitutional_basis: str,
        constitutional_issue: str,
        precedent_map: dict[str, dict[str, list[dict[str, str]]]],
    ) -> list[dict[str, str]]:
        """Match a constitutional issue to landmark cases from the precedent map.

        Searches sub-categories under the given basis for keyword overlap
        with the issue description. Returns matching case entries.
        """
        basis_map = precedent_map.get(constitutional_basis, {})
        if not basis_map:
            return []

        issue_lower = constitutional_issue.lower()
        matched: list[dict[str, str]] = []

        for sub_category, cases in basis_map.items():
            # Check if sub-category keywords appear in the issue text
            keywords = sub_category.replace("_", " ").split()
            if any(kw in issue_lower for kw in keywords):
                matched.extend(cases)

        # If no sub-category matched, return cases from "general" if it exists
        if not matched and "general" in basis_map:
            matched.extend(basis_map["general"])

        return matched[:3]  # Cap at 3 most relevant

    async def lookup_precedent(
        self,
        constitutional_basis: str,
        constitutional_issue: str,
        precedent_map: dict[str, dict[str, list[dict[str, str]]]],
    ) -> list[VerifiedCitation]:
        """Match precedent from the map and verify each via CourtListener API."""
        matches = self.match_precedent(
            constitutional_basis, constitutional_issue, precedent_map
        )
        if not matches:
            return []

        # Build text block with all citation strings for batch verification
        citation_text = " ".join(m["citation"] for m in matches)
        verified = await self.verify_citations(citation_text)

        # Map verified results back; for unmatched, create unverified entries
        verified_by_name: dict[str, VerifiedCitation] = {}
        for v in verified:
            verified_by_name[v.case_name.lower()] = v

        results: list[VerifiedCitation] = []
        for m in matches:
            case_lower = m["case"].lower()
            if case_lower in verified_by_name:
                vc = verified_by_name[case_lower]
                vc.relevance = f"Landmark — {constitutional_basis}"
                results.append(vc)
            else:
                # Partially matched or unverified
                results.append(VerifiedCitation(
                    case_name=m["case"],
                    citation=m["citation"],
                    courtlistener_url="",
                    verified=False,
                    relevance=f"Landmark — {constitutional_basis}",
                ))

        return results
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_courtlistener_precedent.py -v`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/osint_core/services/courtlistener.py tests/test_courtlistener_precedent.py
git commit -m "feat: add precedent lookup to CourtListener client"
```

---

### Task 6: DeepAnalyzer Service

**Files:**
- Create: `src/osint_core/services/deep_analyzer.py`
- Create: `tests/test_deep_analyzer.py`

- [ ] **Step 1: Write tests**

```python
"""Tests for DeepAnalyzer service."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from osint_core.services.deep_analyzer import DeepAnalyzer, _POLICY_ANALYSIS_SCHEMA, _INCIDENT_ANALYSIS_SCHEMA


def _make_lead(*, lead_type: str = "policy", event_ids: list | None = None) -> MagicMock:
    lead = MagicMock()
    lead.id = uuid.uuid4()
    lead.lead_type = lead_type
    lead.title = "Test Policy"
    lead.summary = "A university policy about speech."
    lead.institution = "UC Berkeley"
    lead.jurisdiction = "CA"
    lead.constitutional_basis = ["1A-free-speech"]
    lead.severity = "medium"
    lead.confidence = 0.8
    lead.event_ids = event_ids or [uuid.uuid4()]
    lead.plan_id = "cal-prospecting"
    lead.deep_analysis = None
    lead.analysis_status = "pending"
    return lead


def _make_event(*, minio_uri: str | None = "minio://osint-artifacts/policy.html") -> MagicMock:
    event = MagicMock()
    event.id = uuid.uuid4()
    event.metadata_ = {"minio_uri": minio_uri, "document_type": "html"} if minio_uri else {}
    event.raw_excerpt = "https://example.edu/policy"
    event.title = "Test Policy"
    return event


SAMPLE_POLICY_ANALYSIS = {
    "provisions": [
        {
            "section_reference": "§ 4.2",
            "quoted_language": "Students must use preferred pronouns.",
            "constitutional_issue": "Compelled speech",
            "constitutional_basis": "1A-free-speech",
            "severity": "high",
            "affected_population": "All students",
            "facial_or_as_applied": "facial",
        }
    ],
    "document_summary": "Policy regulating campus speech.",
    "overall_assessment": "Contains one actionable provision.",
    "actionable": True,
}

SAMPLE_INCIDENT_ANALYSIS = {
    "incident_summary": "Professor terminated for classroom speech.",
    "rights_violated": ["1A-free-speech"],
    "individuals_identified": [{"name": "Dr. Smith", "role": "faculty"}],
    "institution": "UC Berkeley",
    "corroboration_strength": "strong",
    "corroboration_notes": "Confirmed by multiple news sources.",
    "actionable": True,
}


class TestAnalyzePolicy:
    @pytest.mark.asyncio
    async def test_analyzes_policy_document(self) -> None:
        analyzer = DeepAnalyzer(precedent_map={})
        lead = _make_lead(lead_type="policy")
        event = _make_event()

        with (
            patch.object(analyzer, "_retrieve_document", new_callable=AsyncMock, return_value=b"<p>Policy text</p>"),
            patch.object(analyzer, "_get_document_type", return_value="html"),
            patch("osint_core.services.deep_analyzer.llm_chat_completion", new_callable=AsyncMock, return_value=json.dumps(SAMPLE_POLICY_ANALYSIS)),
            patch.object(analyzer, "_attach_precedent", new_callable=AsyncMock, return_value=SAMPLE_POLICY_ANALYSIS),
        ):
            result = await analyzer.analyze_lead(lead, event)

        assert result["actionable"] is True
        assert len(result["provisions"]) == 1
        assert result["provisions"][0]["section_reference"] == "§ 4.2"

    @pytest.mark.asyncio
    async def test_non_actionable_policy(self) -> None:
        analyzer = DeepAnalyzer(precedent_map={})
        lead = _make_lead(lead_type="policy")
        event = _make_event()

        empty_result = {
            "provisions": [],
            "document_summary": "Administrative policy.",
            "overall_assessment": "No constitutional issues.",
            "actionable": False,
        }

        with (
            patch.object(analyzer, "_retrieve_document", new_callable=AsyncMock, return_value=b"<p>Admin stuff</p>"),
            patch.object(analyzer, "_get_document_type", return_value="html"),
            patch("osint_core.services.deep_analyzer.llm_chat_completion", new_callable=AsyncMock, return_value=json.dumps(empty_result)),
            patch.object(analyzer, "_attach_precedent", new_callable=AsyncMock, return_value=empty_result),
        ):
            result = await analyzer.analyze_lead(lead, event)

        assert result["actionable"] is False
        assert result["provisions"] == []


class TestAnalyzeIncident:
    @pytest.mark.asyncio
    async def test_analyzes_incident(self) -> None:
        analyzer = DeepAnalyzer(precedent_map={})
        lead = _make_lead(lead_type="incident")
        event = _make_event(minio_uri=None)
        event.raw_excerpt = "https://example.com/article"

        with (
            patch.object(analyzer, "_fetch_article_content", new_callable=AsyncMock, return_value="Article about professor firing."),
            patch("osint_core.services.deep_analyzer.llm_chat_completion", new_callable=AsyncMock, return_value=json.dumps(SAMPLE_INCIDENT_ANALYSIS)),
        ):
            result = await analyzer.analyze_lead(lead, event)

        assert result["actionable"] is True
        assert result["corroboration_strength"] == "strong"


class TestNoSourceMaterial:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_document(self) -> None:
        analyzer = DeepAnalyzer(precedent_map={})
        lead = _make_lead(lead_type="policy")
        event = _make_event(minio_uri=None)
        event.raw_excerpt = None

        result = await analyzer.analyze_lead(lead, event)
        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_deep_analyzer.py -v`
Expected: ImportError — module does not exist yet.

- [ ] **Step 3: Implement DeepAnalyzer**

```python
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
    "4. Assess severity (how clearly does this violate established precedent?)\n"
    "5. Identify the affected population\n"
    "6. Determine if this is a facial challenge or as-applied\n\n"
    "If the document contains NO constitutional issues, return an empty provisions "
    "array and set actionable to false. Do not stretch to find issues that aren't there.\n\n"
    "CRITICAL: Only quote language that actually appears in the document. "
    "Do not fabricate or paraphrase policy text."
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
    "If the incident does not involve constitutional rights, set actionable to false."
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
        """
        if lead.lead_type == "policy":
            return await self._analyze_policy(lead, event)
        return await self._analyze_incident(lead, event)

    # ------------------------------------------------------------------
    # Policy analysis
    # ------------------------------------------------------------------

    async def _analyze_policy(self, lead: Any, event: Any) -> dict[str, Any] | None:
        metadata = event.metadata_ or {}
        minio_uri = metadata.get("minio_uri")

        if not minio_uri:
            logger.info("deep_analysis_no_source", lead_id=str(lead.id), reason="no minio_uri")
            return None

        doc_bytes = await self._retrieve_document(minio_uri)
        if not doc_bytes:
            return None

        doc_type = self._get_document_type(metadata, minio_uri)
        text = DocumentExtractor.extract(doc_bytes, doc_type)

        if not text or not text.strip():
            logger.info("deep_analysis_empty_document", lead_id=str(lead.id))
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
                    json_schema=_POLICY_ANALYSIS_SCHEMA,
                )
                result = json.loads(content)
            except Exception as exc:
                logger.warning("deep_analysis_llm_failed", lead_id=str(lead.id), chunk=chunk.index, error=str(exc))
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
            logger.info("deep_analysis_no_source", lead_id=str(lead.id), reason="no article content")
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
                json_schema=_INCIDENT_ANALYSIS_SCHEMA,
            )
            return json.loads(response)
        except Exception as exc:
            logger.warning("deep_analysis_llm_failed", lead_id=str(lead.id), error=str(exc))
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
            logger.warning("deep_analysis_minio_failed", uri=minio_uri, error=str(exc))
            return None

    @staticmethod
    def _get_document_type(metadata: dict[str, Any], minio_uri: str) -> str:
        """Determine document type from metadata or URI."""
        doc_type = metadata.get("document_type", "")
        if doc_type in ("pdf", "html"):
            return doc_type
        if minio_uri.lower().endswith(".pdf"):
            return "pdf"
        return "html"

    async def _fetch_article_content(self, event: Any) -> str | None:
        """Fetch article content for incident leads."""
        # Try raw_excerpt as URL
        url = None
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
            logger.warning("deep_analysis_fetch_failed", url=url, error=str(exc))
            # Fall back to summary
            return getattr(event, "nlp_summary", None) or getattr(event, "summary", None)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_deep_analyzer.py -v`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/osint_core/services/deep_analyzer.py tests/test_deep_analyzer.py
git commit -m "feat: add DeepAnalyzer service for clause-level constitutional analysis"
```

---

### Task 7: Wire analyze_leads_task into Prospecting Worker

**Files:**
- Modify: `src/osint_core/workers/prospecting.py`
- Create: `tests/test_analyze_leads_task.py`

- [ ] **Step 1: Write tests**

```python
"""Tests for analyze_leads_task in prospecting worker."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_lead(*, analysis_status: str = "pending", lead_type: str = "policy") -> MagicMock:
    lead = MagicMock()
    lead.id = uuid.uuid4()
    lead.lead_type = lead_type
    lead.analysis_status = analysis_status
    lead.plan_id = "cal-prospecting"
    lead.event_ids = [uuid.uuid4()]
    lead.severity = "medium"
    return lead


def _make_event(*, minio_uri: str | None = "minio://bucket/key") -> MagicMock:
    event = MagicMock()
    event.id = uuid.uuid4()
    event.metadata_ = {"minio_uri": minio_uri} if minio_uri else {}
    event.raw_excerpt = "https://example.com"
    event.nlp_summary = "Summary"
    return event


class TestAnalyzeLeadsAsync:
    @pytest.mark.asyncio
    async def test_analyzes_pending_leads(self) -> None:
        from osint_core.workers.prospecting import _analyze_leads_async

        lead = _make_lead()
        event = _make_event()
        analysis_result = {"actionable": True, "provisions": [{"section_reference": "§1"}]}

        # Mock DB
        db = AsyncMock()
        # First execute: select pending leads
        lead_result = MagicMock()
        lead_result.scalars.return_value.all.return_value = [lead]
        # Second execute: select event by id
        event_result = MagicMock()
        event_result.scalar_one_or_none.return_value = event

        db.execute = AsyncMock(side_effect=[lead_result, event_result])
        db.commit = AsyncMock()

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=db)
        ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("osint_core.workers.prospecting.async_session", return_value=ctx),
            patch("osint_core.workers.prospecting.DeepAnalyzer") as MockAnalyzer,
        ):
            mock_instance = MockAnalyzer.return_value
            mock_instance.analyze_lead = AsyncMock(return_value=analysis_result)

            result = await _analyze_leads_async("cal-prospecting")

        assert result["analyzed"] >= 1
        assert lead.analysis_status == "completed"
        assert lead.deep_analysis == analysis_result

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self) -> None:
        from osint_core.workers.prospecting import _analyze_leads_async

        with patch("osint_core.workers.prospecting._is_deep_analysis_enabled", return_value=False):
            result = await _analyze_leads_async("cal-prospecting")

        assert result["status"] == "skipped"
        assert result["reason"] == "deep_analysis_disabled"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_analyze_leads_task.py -v`
Expected: ImportError — `_analyze_leads_async` does not exist yet.

- [ ] **Step 3: Add analyze_leads_task and _analyze_leads_async to prospecting.py**

Add these imports at the top of `src/osint_core/workers/prospecting.py`:

```python
from osint_core.services.deep_analyzer import DeepAnalyzer
```

Add a helper function to check if deep analysis is enabled:

```python
def _is_deep_analysis_enabled(plan_content: dict[str, Any] | None = None) -> bool:
    """Check if deep analysis is enabled for a plan."""
    if plan_content is None:
        return False
    custom = plan_content.get("custom", {})
    return bool(custom.get("deep_analysis_enabled", False))


def _get_precedent_map(plan_content: dict[str, Any]) -> dict[str, dict[str, list[dict[str, str]]]]:
    """Extract precedent map from plan content."""
    return plan_content.get("custom", {}).get("precedent_map", {})
```

Add the async implementation:

```python
async def _analyze_leads_async(plan_id: str) -> dict[str, Any]:
    """Run deep analysis on all pending leads for a plan."""
    from osint_core.db import async_session
    from osint_core.models.event import Event
    from osint_core.models.plan_version import PlanVersion

    async with async_session() as db:
        # Load active plan content
        plan_stmt = (
            select(PlanVersion)
            .where(PlanVersion.plan_id == plan_id, PlanVersion.is_active.is_(True))
            .limit(1)
        )
        plan_result = await db.execute(plan_stmt)
        plan_version = plan_result.scalar_one_or_none()

        if not plan_version:
            return {"status": "skipped", "reason": "no_active_plan"}

        plan_content = plan_version.content or {}

        if not _is_deep_analysis_enabled(plan_content):
            return {"status": "skipped", "reason": "deep_analysis_disabled"}

        custom = plan_content.get("custom", {})
        relevance_gate = bool(custom.get("deep_analysis_relevance_gate", False))
        precedent_map = _get_precedent_map(plan_content)

        # Select pending leads
        stmt = (
            select(Lead)
            .where(
                Lead.plan_id == plan_id,
                Lead.analysis_status == "pending",
            )
        )
        lead_result = await db.execute(stmt)
        leads = list(lead_result.scalars().all())

        if not leads:
            return {"status": "completed", "analyzed": 0, "plan_id": plan_id}

        analyzer = DeepAnalyzer(precedent_map=precedent_map)
        analyzed = 0
        failed = 0

        for lead in leads:
            # Get the first event for source material
            if not lead.event_ids:
                lead.analysis_status = "no_source_material"
                continue

            event_stmt = select(Event).where(Event.id == lead.event_ids[0])
            event_result = await db.execute(event_stmt)
            event = event_result.scalar_one_or_none()

            if not event:
                lead.analysis_status = "no_source_material"
                continue

            # Optional relevance gate
            if relevance_gate:
                relevance = getattr(event, "nlp_relevance", None)
                if isinstance(relevance, str) and relevance.strip().lower() != "relevant":
                    lead.analysis_status = "no_source_material"
                    continue

            try:
                result = await analyzer.analyze_lead(lead, event)
            except Exception as exc:
                logger.warning("deep_analysis_failed", lead_id=str(lead.id), error=str(exc))
                lead.analysis_status = "failed"
                failed += 1
                continue

            if result is None:
                lead.analysis_status = "no_source_material"
                continue

            lead.deep_analysis = result
            lead.analysis_status = "completed"

            # Downgrade non-actionable leads
            if not result.get("actionable", True):
                lead.severity = "info"

            analyzed += 1

        await db.commit()

    return {
        "status": "completed",
        "plan_id": plan_id,
        "analyzed": analyzed,
        "failed": failed,
        "total": len(leads),
    }
```

Add the Celery task:

```python
@celery_app.task(bind=True, name="osint.analyze_leads", max_retries=2)
def analyze_leads_task(self: Any, plan_id: str) -> dict[str, Any]:
    """Run deep constitutional analysis on pending leads.

    Called after match_leads completes. Analyzes full policy documents
    and incident reports for clause-level constitutional issues.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_analyze_leads_async(plan_id))
    except Exception as exc:
        logger.exception("Deep analysis failed for plan %s", plan_id)
        raise self.retry(
            exc=exc, countdown=min(2 ** self.request.retries * 30, 300),
        ) from exc
    finally:
        loop.close()
```

Add the task route to `celery_app.py` if not auto-routed:

In `src/osint_core/workers/celery_app.py`, add to `task_routes`:

```python
"osint.analyze_leads": {"queue": "enrich"},
```

- [ ] **Step 4: Wire analyze_leads into the pipeline**

In the `match_leads_task` function, after the async call returns successfully, dispatch the deep analysis task. Find where `match_leads_task` returns its result and add before the return:

```python
    # Dispatch deep analysis after successful lead matching
    from osint_core.workers.prospecting import analyze_leads_task
    analyze_leads_task.delay(plan_id)
```

- [ ] **Step 5: Update the pipeline guard to also check for pending analyze_leads tasks**

In `_has_pending_match_leads_tasks()`, also check for `osint.analyze_leads`:

```python
_ANALYSIS_TASK_NAME = "osint.analyze_leads"
```

And update the guard check to include both task names.

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_analyze_leads_task.py -v`
Expected: All tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/osint_core/workers/prospecting.py src/osint_core/workers/celery_app.py tests/test_analyze_leads_task.py
git commit -m "feat: wire analyze_leads_task into prospecting pipeline"
```

---

### Task 8: Update Report Generator to Render Deep Analysis

**Files:**
- Modify: `src/osint_core/services/prospecting_report.py`
- Modify: `src/osint_core/templates/prospecting_report.html`

- [ ] **Step 1: Update report generator to use deep_analysis when available**

In `prospecting_report.py`, find the loop where lead contexts are built (inside `generate_report`). For each lead, check if `lead.analysis_status == "completed"` and `lead.deep_analysis` exists. If so, skip the `_generate_narrative()` call and build the context from deep_analysis instead.

Add this function:

```python
def _build_deep_analysis_context(lead: Lead) -> dict[str, Any]:
    """Build template context from deep analysis results."""
    analysis = lead.deep_analysis or {}

    if lead.lead_type == "policy":
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
```

In the lead-processing loop, add a conditional before calling `_generate_narrative()`:

```python
    if lead.analysis_status == "completed" and lead.deep_analysis:
        # Skip non-actionable leads
        if not lead.deep_analysis.get("actionable", True):
            continue
        lead_ctx = _build_deep_analysis_context(lead)
    else:
        # Existing shallow narrative path
        narrative = await _generate_narrative(lead)
        lead_ctx = {
            "has_deep_analysis": False,
            # ... existing context building ...
        }
```

- [ ] **Step 2: Update the HTML template**

Add new template blocks to `src/osint_core/templates/prospecting_report.html` for deep analysis rendering.

Inside the lead iteration block, add a conditional for `has_deep_analysis`:

```html
{% if lead.has_deep_analysis and lead.lead_type == 'policy' %}
  <div class="lead-section">
    <h3>{{ lead.title }}</h3>
    <p class="lead-meta">
      {{ lead.institution }} | {{ lead.jurisdiction or 'N/A' }} |
      Severity: {{ lead.severity }} | Confidence: {{ "%.0f"|format(lead.confidence * 100) }}%
    </p>
    <p>{{ lead.document_summary }}</p>
    <p><strong>Assessment:</strong> {{ lead.overall_assessment }}</p>

    {% for provision in lead.provisions %}
    <div class="provision">
      <h4>{{ provision.section_reference }} — {{ provision.constitutional_issue }}</h4>
      <blockquote>{{ provision.quoted_language }}</blockquote>
      <p>
        <strong>Constitutional basis:</strong> {{ provision.constitutional_basis }}<br>
        <strong>Severity:</strong> {{ provision.severity }} —
        {{ provision.facial_or_as_applied }} challenge<br>
        <strong>Affected population:</strong> {{ provision.affected_population }}
      </p>
      {% if provision.precedent %}
      <p><strong>Relevant precedent:</strong></p>
      <ul>
        {% for p in provision.precedent %}
        <li>
          <em>{{ p.case_name }}</em>, {{ p.citation }}
          {% if p.verified %}✓{% else %}⚠{% endif %}
          {% if p.holding_summary %} — {{ p.holding_summary }}{% endif %}
        </li>
        {% endfor %}
      </ul>
      {% endif %}
    </div>
    {% endfor %}
  </div>

{% elif lead.has_deep_analysis and lead.lead_type == 'incident' %}
  <div class="lead-section">
    <h3>{{ lead.title }}</h3>
    <p class="lead-meta">
      {{ lead.institution }} | {{ lead.jurisdiction or 'N/A' }} |
      Severity: {{ lead.severity }} | Confidence: {{ "%.0f"|format(lead.confidence * 100) }}%
    </p>
    <p>{{ lead.incident_summary }}</p>
    <p>
      <strong>Rights violated:</strong> {{ lead.rights_violated | join(', ') }}<br>
      <strong>Corroboration:</strong> {{ lead.corroboration_strength }} — {{ lead.corroboration_notes }}
    </p>
    {% if lead.individuals_identified %}
    <p><strong>Individuals identified:</strong></p>
    <ul>
      {% for person in lead.individuals_identified %}
      <li>{{ person.name }} ({{ person.role }})</li>
      {% endfor %}
    </ul>
    {% endif %}
  </div>

{% else %}
  {# Existing shallow narrative rendering #}
```

- [ ] **Step 3: Run existing report tests**

Run: `pytest tests/test_prospecting_report.py -v`
Expected: All existing tests still pass.

- [ ] **Step 4: Commit**

```bash
git add src/osint_core/services/prospecting_report.py src/osint_core/templates/prospecting_report.html
git commit -m "feat: render deep analysis provisions in prospecting reports"
```

---

### Task 9: Add Plan Config

**Files:**
- Modify: `plans/cal-prospecting.yaml`

- [ ] **Step 1: Add deep analysis config and precedent map**

Add under the `custom:` section in `plans/cal-prospecting.yaml`:

```yaml
  deep_analysis_enabled: true
  deep_analysis_relevance_gate: false
  precedent_map:
    1A-free-speech:
      compelled_speech:
        - case: "West Virginia State Board of Education v. Barnette"
          citation: "319 U.S. 624 (1943)"
        - case: "Janus v. AFSCME"
          citation: "585 U.S. 878 (2018)"
        - case: "303 Creative LLC v. Elenis"
          citation: "600 U.S. 570 (2023)"
      speech_codes:
        - case: "Tinker v. Des Moines Independent Community School District"
          citation: "393 U.S. 503 (1969)"
        - case: "Healy v. James"
          citation: "408 U.S. 169 (1972)"
        - case: "Papish v. Board of Curators of the University of Missouri"
          citation: "410 U.S. 667 (1973)"
      viewpoint_discrimination:
        - case: "Rosenberger v. Rector and Visitors of the University of Virginia"
          citation: "515 U.S. 819 (1995)"
        - case: "Board of Regents of the University of Wisconsin System v. Southworth"
          citation: "529 U.S. 217 (2000)"
    1A-religion:
      free_exercise:
        - case: "Kennedy v. Bremerton School District"
          citation: "597 U.S. 507 (2022)"
        - case: "Fulton v. City of Philadelphia"
          citation: "593 U.S. 522 (2021)"
      general:
        - case: "Church of the Lukumi Babalu Aye v. City of Hialeah"
          citation: "508 U.S. 520 (1993)"
    14A-due-process:
      campus_discipline:
        - case: "Mathews v. Eldridge"
          citation: "424 U.S. 319 (1976)"
        - case: "Goss v. Lopez"
          citation: "419 U.S. 565 (1975)"
        - case: "Doe v. Baum"
          citation: "903 F.3d 575 (6th Cir. 2018)"
    14A-equal-protection:
      general:
        - case: "Reed v. Reed"
          citation: "404 U.S. 71 (1971)"
        - case: "Students for Fair Admissions v. President and Fellows of Harvard College"
          citation: "600 U.S. 181 (2023)"
    parental-rights:
      general:
        - case: "Troxel v. Granville"
          citation: "530 U.S. 57 (2000)"
        - case: "Pierce v. Society of Sisters"
          citation: "268 U.S. 510 (1925)"
```

- [ ] **Step 2: Validate YAML syntax**

Run: `python3 -c "import yaml; yaml.safe_load(open('plans/cal-prospecting.yaml'))"`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add plans/cal-prospecting.yaml
git commit -m "feat: add deep analysis config and precedent map to CAL plan"
```

---

### Task 10: Integration Test

**Files:**
- Create: `tests/test_deep_analysis_integration.py`

- [ ] **Step 1: Write integration test**

```python
"""Integration tests for the deep analysis pipeline."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


SAMPLE_PLAN_CONTENT = {
    "custom": {
        "deep_analysis_enabled": True,
        "deep_analysis_relevance_gate": False,
        "precedent_map": {
            "1A-free-speech": {
                "compelled_speech": [
                    {"case": "West Virginia v. Barnette", "citation": "319 U.S. 624 (1943)"},
                ],
            },
        },
    },
    "scoring": {"source_reputation": {}},
}

SAMPLE_POLICY_RESULT = {
    "provisions": [
        {
            "section_reference": "§ 5.1",
            "quoted_language": "All students must attend mandatory training.",
            "constitutional_issue": "Compelled speech in mandatory training",
            "constitutional_basis": "1A-free-speech",
            "severity": "high",
            "affected_population": "All enrolled students",
            "facial_or_as_applied": "facial",
        }
    ],
    "document_summary": "Student conduct policy with speech requirements.",
    "overall_assessment": "Contains one high-severity compelled speech provision.",
    "actionable": True,
}


class TestFullPipeline:
    @pytest.mark.asyncio
    async def test_analyze_leads_produces_deep_analysis(self) -> None:
        """Verify the full pipeline: pending lead → deep analysis → completed."""
        from osint_core.workers.prospecting import _analyze_leads_async

        lead = MagicMock()
        lead.id = uuid.uuid4()
        lead.lead_type = "policy"
        lead.title = "Student Conduct Policy"
        lead.institution = "Test University"
        lead.jurisdiction = "TX"
        lead.constitutional_basis = ["1A-free-speech"]
        lead.severity = "medium"
        lead.confidence = 0.8
        lead.event_ids = [uuid.uuid4()]
        lead.plan_id = "cal-prospecting"
        lead.analysis_status = "pending"
        lead.deep_analysis = None

        event = MagicMock()
        event.id = lead.event_ids[0]
        event.metadata_ = {"minio_uri": "minio://osint-artifacts/test.html", "document_type": "html"}
        event.nlp_relevance = "relevant"

        plan_version = MagicMock()
        plan_version.plan_id = "cal-prospecting"
        plan_version.content = SAMPLE_PLAN_CONTENT
        plan_version.is_active = True

        db = AsyncMock()
        # Call 1: select plan version
        plan_result = MagicMock()
        plan_result.scalar_one_or_none.return_value = plan_version
        # Call 2: select pending leads
        lead_result = MagicMock()
        lead_result.scalars.return_value.all.return_value = [lead]
        # Call 3: select event
        event_result = MagicMock()
        event_result.scalar_one_or_none.return_value = event

        db.execute = AsyncMock(side_effect=[plan_result, lead_result, event_result])
        db.commit = AsyncMock()

        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=db)
        ctx.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("osint_core.workers.prospecting.async_session", return_value=ctx),
            patch("osint_core.services.deep_analyzer.DeepAnalyzer._retrieve_document", new_callable=AsyncMock, return_value=b"<p>Policy text</p>"),
            patch("osint_core.services.deep_analyzer.llm_chat_completion", new_callable=AsyncMock, return_value=json.dumps(SAMPLE_POLICY_RESULT)),
            patch("osint_core.services.deep_analyzer.CourtListenerClient.lookup_precedent", new_callable=AsyncMock, return_value=[]),
        ):
            result = await _analyze_leads_async("cal-prospecting")

        assert result["status"] == "completed"
        assert result["analyzed"] == 1
        assert lead.analysis_status == "completed"
        assert lead.deep_analysis["actionable"] is True
        assert len(lead.deep_analysis["provisions"]) == 1
        assert lead.deep_analysis["provisions"][0]["section_reference"] == "§ 5.1"
```

- [ ] **Step 2: Run integration test**

Run: `pytest tests/test_deep_analysis_integration.py -v`
Expected: All tests pass.

- [ ] **Step 3: Run all tests**

Run: `pytest tests/ -v --tb=short`
Expected: All tests pass, including existing tests.

- [ ] **Step 4: Commit**

```bash
git add tests/test_deep_analysis_integration.py
git commit -m "test: add integration test for deep analysis pipeline"
```
