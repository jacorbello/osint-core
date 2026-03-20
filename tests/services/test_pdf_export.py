"""Tests for the PDF export service."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from osint_core.services.pdf_export import (
    BRIEF_PDF_BUCKET,
    _markdown_to_html,
    generate_and_upload_pdf,
    render_brief_pdf,
    upload_pdf_to_minio,
)

# ---------------------------------------------------------------------------
# _markdown_to_html
# ---------------------------------------------------------------------------


class TestMarkdownToHtml:
    """Tests for the markdown-to-HTML converter."""

    def test_contains_body_content(self):
        html = _markdown_to_html("# Hello World\n\nSome content here.")
        assert "Hello World" in html
        assert "Some content here" in html

    def test_includes_classification_header(self):
        html = _markdown_to_html("test", classification="SECRET")
        assert "SECRET" in html

    def test_includes_plan_name(self):
        html = _markdown_to_html("test", plan_name="my-plan")
        assert "my-plan" in html

    def test_includes_title(self):
        html = _markdown_to_html("test", title="Brief Title")
        assert "Brief Title" in html

    def test_default_classification_is_unclassified(self):
        html = _markdown_to_html("test")
        assert "UNCLASSIFIED" in html

    def test_includes_timestamp(self):
        html = _markdown_to_html("test")
        # Should contain a UTC timestamp pattern
        assert "UTC" in html

    def test_renders_markdown_tables(self):
        md = "| Col1 | Col2 |\n|------|------|\n| A    | B    |"
        html = _markdown_to_html(md)
        assert "<table>" in html
        assert "<th>" in html

    def test_renders_fenced_code(self):
        md = "```\ncode block\n```"
        html = _markdown_to_html(md)
        assert "<code>" in html


# ---------------------------------------------------------------------------
# render_brief_pdf
# ---------------------------------------------------------------------------


class TestRenderBriefPdf:
    """Tests for PDF rendering (mocks weasyprint)."""

    @patch("osint_core.services.pdf_export.HTML")
    def test_returns_pdf_bytes(self, mock_html_cls: MagicMock):
        mock_html_instance = MagicMock()
        mock_html_instance.write_pdf.return_value = b"%PDF-1.4 fake"
        mock_html_cls.return_value = mock_html_instance

        result = render_brief_pdf("# Hello", title="Test Brief")

        assert result == b"%PDF-1.4 fake"
        mock_html_cls.assert_called_once()
        mock_html_instance.write_pdf.assert_called_once()

    @patch("osint_core.services.pdf_export.HTML")
    def test_passes_title_to_html(self, mock_html_cls: MagicMock):
        mock_html_instance = MagicMock()
        mock_html_instance.write_pdf.return_value = b"%PDF"
        mock_html_cls.return_value = mock_html_instance

        render_brief_pdf("content", title="My Title", classification="TOP SECRET")

        html_string = mock_html_cls.call_args[1]["string"]
        assert "My Title" in html_string
        assert "TOP SECRET" in html_string


# ---------------------------------------------------------------------------
# upload_pdf_to_minio
# ---------------------------------------------------------------------------


class TestUploadPdfToMinio:
    """Tests for MinIO upload (mocks minio client)."""

    @patch("osint_core.services.pdf_export.Minio")
    def test_creates_bucket_if_not_exists(self, mock_minio_cls: MagicMock):
        mock_client = MagicMock()
        mock_client.bucket_exists.return_value = False
        mock_minio_cls.return_value = mock_client

        upload_pdf_to_minio(b"%PDF", "briefs/test.pdf")

        mock_client.make_bucket.assert_called_once_with(BRIEF_PDF_BUCKET)

    @patch("osint_core.services.pdf_export.Minio")
    def test_skips_bucket_creation_if_exists(self, mock_minio_cls: MagicMock):
        mock_client = MagicMock()
        mock_client.bucket_exists.return_value = True
        mock_minio_cls.return_value = mock_client

        upload_pdf_to_minio(b"%PDF", "briefs/test.pdf")

        mock_client.make_bucket.assert_not_called()

    @patch("osint_core.services.pdf_export.Minio")
    def test_returns_minio_uri(self, mock_minio_cls: MagicMock):
        mock_client = MagicMock()
        mock_client.bucket_exists.return_value = True
        mock_minio_cls.return_value = mock_client

        uri = upload_pdf_to_minio(b"%PDF-data", "briefs/abc.pdf")

        assert uri == f"minio://{BRIEF_PDF_BUCKET}/briefs/abc.pdf"

    @patch("osint_core.services.pdf_export.Minio")
    def test_puts_object_with_correct_params(self, mock_minio_cls: MagicMock):
        mock_client = MagicMock()
        mock_client.bucket_exists.return_value = True
        mock_minio_cls.return_value = mock_client

        pdf_data = b"%PDF-1.4 test data"
        upload_pdf_to_minio(pdf_data, "briefs/xyz.pdf")

        mock_client.put_object.assert_called_once()
        call_args = mock_client.put_object.call_args
        assert call_args[0][0] == BRIEF_PDF_BUCKET
        assert call_args[0][1] == "briefs/xyz.pdf"
        assert call_args[1]["length"] == len(pdf_data)
        assert call_args[1]["content_type"] == "application/pdf"

    @patch("osint_core.services.pdf_export.Minio")
    def test_custom_bucket(self, mock_minio_cls: MagicMock):
        mock_client = MagicMock()
        mock_client.bucket_exists.return_value = True
        mock_minio_cls.return_value = mock_client

        uri = upload_pdf_to_minio(b"%PDF", "key.pdf", bucket="custom-bucket")

        assert uri == "minio://custom-bucket/key.pdf"
        mock_client.bucket_exists.assert_called_once_with("custom-bucket")


# ---------------------------------------------------------------------------
# generate_and_upload_pdf (integration of render + upload)
# ---------------------------------------------------------------------------


class TestGenerateAndUploadPdf:
    """Tests for the combined generate-and-upload function."""

    @patch("osint_core.services.pdf_export.upload_pdf_to_minio")
    @patch("osint_core.services.pdf_export.render_brief_pdf")
    def test_calls_render_and_upload(
        self, mock_render: MagicMock, mock_upload: MagicMock
    ):
        mock_render.return_value = b"%PDF-fake"
        mock_upload.return_value = "minio://osint-briefs/briefs/abc-123.pdf"

        uri = generate_and_upload_pdf(
            "abc-123",
            "# Brief content",
            title="Test",
            plan_name="plan-1",
        )

        mock_render.assert_called_once_with(
            "# Brief content",
            title="Test",
            classification="UNCLASSIFIED",
            plan_name="plan-1",
        )
        mock_upload.assert_called_once_with(b"%PDF-fake", "briefs/abc-123.pdf")
        assert uri == "minio://osint-briefs/briefs/abc-123.pdf"
