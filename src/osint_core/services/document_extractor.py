"""Document text extraction and chunking for deep analysis.

Extracts readable text from HTML (preserving section structure) and PDF
(preserving page markers). Chunks large documents with configurable overlap
and section-boundary-aware splitting.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from bs4 import BeautifulSoup
from langdetect import DetectorFactory
from langdetect import detect as _langdetect_detect

DetectorFactory.seed = 0

_HEADING_MAP = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}

DEFAULT_MAX_CHARS = 300_000
DEFAULT_OVERLAP_CHARS = 20_000

_SECTION_RE = re.compile(
    r"(?:^|\n)(?=(?:#{1,6}\s|§\s*\d|Article\s+\d|Section\s+\d|Rule\s+\d|PART\s+\d))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ExtractionResult:
    """Result of a pre-analysis quality gate check."""

    passed: bool
    failure_reason: str | None = None


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

        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        for tag_name, prefix in _HEADING_MAP.items():
            for tag in soup.find_all(tag_name):
                text = tag.get_text(strip=True)
                tag.replace_with(f"\n\n{prefix} {text}\n\n")

        text = soup.get_text(separator="\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def extract_pdf(pdf_bytes: bytes) -> str:
        """Extract text from PDF bytes, preserving page markers."""
        import fitz

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages: list[str] = []
        for i, page in enumerate(doc, start=1):
            text = page.get_text().strip()
            pages.append(f"[Page {i}]\n{text}")
        doc.close()
        return "\n\n".join(pages)

    @staticmethod
    def validate_encoding(text: str, threshold: float = 0.05) -> ExtractionResult:
        """Check for garbled characters in extracted text.

        Flags U+FFFD replacement chars, control chars (except \\t\\n\\r),
        and private-use-area codepoints. Returns ExtractionResult with
        passed=False if the ratio of bad chars >= threshold.
        """
        if not text or not text.strip():
            return ExtractionResult(passed=False, failure_reason="no_content")

        bad = 0
        for ch in text:
            cp = ord(ch)
            if (
                cp == 0xFFFD
                or (cp < 0x20 and ch not in "\t\n\r")
                or 0xE000 <= cp <= 0xF8FF
                or (
                    unicodedata.category(ch) in ("Cc", "Cf")
                    and ch not in "\t\n\r"
                    and cp >= 0x20
                )
            ):
                bad += 1

        ratio = bad / len(text)
        if ratio >= threshold:
            return ExtractionResult(passed=False, failure_reason="extraction_failed")
        return ExtractionResult(passed=True)

    @staticmethod
    def detect_language(text: str) -> str:
        """Detect language of text using langdetect.

        Returns ISO 639-1 code or "unknown" if text is too short (<20 chars)
        or detection fails.
        """
        if len(text.strip()) < 20:
            return "unknown"
        try:
            return _langdetect_detect(text[:1000])
        except Exception:
            return "unknown"

    @staticmethod
    def check_content(text: str, min_chars: int = 100) -> bool:
        """Return True if stripped text has at least min_chars characters."""
        return len(text.strip()) >= min_chars

    @staticmethod
    def extract_pdf_with_fallback(pdf_bytes: bytes) -> str:
        """Extract PDF text with PyMuPDF, falling back to pdfplumber on garbled output."""
        primary = DocumentExtractor.extract_pdf(pdf_bytes)
        result = DocumentExtractor.validate_encoding(primary)
        if result.passed:
            return primary

        # Fallback: try pdfplumber
        import io

        import pdfplumber

        pages: list[str] = []
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                text = (page.extract_text() or "").strip()
                pages.append(f"[Page {i}]\n{text}")
        fallback = "\n\n".join(pages)

        fallback_result = DocumentExtractor.validate_encoding(fallback)
        if fallback_result.passed:
            return fallback

        # Return whichever is less garbled (prefer primary)
        return primary

    @staticmethod
    def extract_toc(text: str) -> str:
        """Extract a table of contents from markdown-style headings."""
        lines: list[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
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
        """Split text into chunks, preferring section boundaries."""
        if len(text) <= max_chars:
            return [DocumentChunk(text=text, index=0, total=1)]

        toc = DocumentExtractor.extract_toc(text)
        preamble = ""
        if document_title or institution:
            parts = [p for p in [document_title, institution] if p]
            preamble = f"Document: {' — '.join(parts)}\n"
        if toc:
            preamble += f"Table of Contents:\n{toc}\n\n---\n\n"

        content_max = max_chars - len(preamble)
        if content_max <= 0:
            content_max = max_chars

        boundaries = [m.start() for m in _SECTION_RE.finditer(text)]
        if not boundaries or boundaries[0] != 0:
            boundaries.insert(0, 0)

        chunks: list[DocumentChunk] = []
        start = 0

        while start < len(text):
            end = start + content_max

            if end >= len(text):
                chunk_text = text[start:]
            else:
                best = end
                for b in reversed(boundaries):
                    if start < b <= end:
                        best = b
                        break
                if best == end:
                    newline_pos = text.rfind("\n\n", start, end)
                    if newline_pos > start:
                        best = newline_pos
                chunk_text = text[start:best]

            full_text = preamble + chunk_text if preamble else chunk_text
            chunks.append(DocumentChunk(text=full_text, index=len(chunks), total=0, toc=toc))

            # Advance past this chunk, backing up by overlap for context.
            # Guarantee forward progress of at least half the content_max.
            next_start = start + len(chunk_text)
            if next_start < len(text) and overlap_chars > 0:
                min_advance = max(content_max // 2, 1)
                next_start = max(next_start - overlap_chars, start + min_advance)
            start = next_start

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
            return DocumentExtractor.extract_pdf_with_fallback(content_bytes)
        return DocumentExtractor.extract_html(content_bytes.decode("utf-8", errors="replace"))
