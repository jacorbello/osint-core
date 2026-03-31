"""Document text extraction and chunking for deep analysis.

Extracts readable text from HTML (preserving section structure) and PDF
(preserving page markers). Chunks large documents with configurable overlap
and section-boundary-aware splitting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

_HEADING_MAP = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}

DEFAULT_MAX_CHARS = 300_000
DEFAULT_OVERLAP_CHARS = 20_000

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

            next_start = start + len(chunk_text)
            if next_start < len(text) and overlap_chars > 0:
                next_start = max(next_start - overlap_chars, start + 1)
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
            return DocumentExtractor.extract_pdf(content_bytes)
        return DocumentExtractor.extract_html(content_bytes.decode("utf-8", errors="replace"))
