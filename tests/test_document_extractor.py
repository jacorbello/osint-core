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
        doc.new_page()
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
        sections = []
        for i in range(10):
            sections.append(f"## Section {i}\n{'Content. ' * 500}")
        text = "\n\n".join(sections)
        chunks = DocumentExtractor.chunk(text, max_chars=2000)
        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk.total == len(chunks)

    def test_overlap_preserves_context(self) -> None:
        sections = [f"## Section {i}\nParagraph {i} content." for i in range(5)]
        text = "\n\n".join(sections)
        chunks = DocumentExtractor.chunk(text, max_chars=100, overlap_chars=30)
        if len(chunks) >= 2:
            assert len(chunks[0].text) > 0
            assert len(chunks[1].text) > 0

    def test_toc_extraction(self) -> None:
        text = "# Main Title\nIntro.\n## Section A\nContent A.\n## Section B\nContent B."
        toc = DocumentExtractor.extract_toc(text)
        assert "Main Title" in toc
        assert "Section A" in toc
        assert "Section B" in toc


class TestDetectType:
    def test_pdf_by_content_type(self) -> None:
        assert DocumentExtractor.detect_type(b"", content_type="application/pdf") == "pdf"

    def test_pdf_by_url(self) -> None:
        assert DocumentExtractor.detect_type(b"", url="https://example.com/doc.pdf") == "pdf"

    def test_pdf_by_magic_bytes(self) -> None:
        assert DocumentExtractor.detect_type(b"%PDF-1.4 rest of file") == "pdf"

    def test_html_default(self) -> None:
        assert DocumentExtractor.detect_type(b"<html>") == "html"
