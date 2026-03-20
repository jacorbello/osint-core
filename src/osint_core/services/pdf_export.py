"""PDF export service — render briefs to PDF and upload to MinIO."""

from __future__ import annotations

import io
import logging
from datetime import UTC, datetime

import markdown as markdown_lib  # type: ignore[import-untyped]
from minio import Minio  # type: ignore[import-untyped]
from weasyprint import HTML  # type: ignore[import-untyped]

from osint_core.config import settings

logger = logging.getLogger(__name__)

# MinIO bucket for storing brief PDFs.
BRIEF_PDF_BUCKET = "osint-briefs"


def _markdown_to_html(
    content_md: str,
    *,
    title: str = "",
    classification: str = "UNCLASSIFIED",
    plan_name: str = "",
) -> str:
    """Convert markdown content to styled HTML suitable for PDF rendering.

    Args:
        content_md: Markdown text to convert.
        title: Brief title for the header.
        classification: Classification marking for the header/footer.
        plan_name: Optional plan name for the header.

    Returns:
        HTML string ready for PDF conversion.
    """
    body_html = markdown_lib.markdown(
        content_md,
        extensions=["tables", "fenced_code", "nl2br"],
    )

    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    header_parts = [f"<strong>{classification}</strong>"]
    if plan_name:
        header_parts.append(f"Plan: {plan_name}")
    header_parts.append(f"Generated: {timestamp}")

    header_line = " &mdash; ".join(header_parts)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{title or 'Intelligence Brief'}</title>
<style>
  @page {{
    size: A4;
    margin: 2cm;
    @top-center {{
      content: "{classification}";
      font-size: 10px;
      color: #666;
    }}
    @bottom-center {{
      content: "Page " counter(page) " of " counter(pages);
      font-size: 10px;
      color: #666;
    }}
  }}
  body {{
    font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
    font-size: 12px;
    line-height: 1.6;
    color: #333;
  }}
  .header {{
    border-bottom: 2px solid #333;
    padding-bottom: 8px;
    margin-bottom: 20px;
    font-size: 10px;
    color: #666;
  }}
  h1 {{ font-size: 20px; margin-top: 20px; }}
  h2 {{ font-size: 16px; margin-top: 16px; }}
  h3 {{ font-size: 14px; margin-top: 12px; }}
  table {{
    border-collapse: collapse;
    width: 100%;
    margin: 10px 0;
  }}
  th, td {{
    border: 1px solid #ddd;
    padding: 6px 10px;
    text-align: left;
  }}
  th {{ background-color: #f5f5f5; font-weight: bold; }}
  code {{
    background-color: #f4f4f4;
    padding: 2px 4px;
    font-size: 11px;
  }}
  pre code {{
    display: block;
    padding: 10px;
    overflow-x: auto;
  }}
</style>
</head>
<body>
  <div class="header">{header_line}</div>
  {body_html}
</body>
</html>"""


def render_brief_pdf(
    content_md: str,
    *,
    title: str = "",
    classification: str = "UNCLASSIFIED",
    plan_name: str = "",
) -> bytes:
    """Render markdown content to a PDF document.

    Args:
        content_md: Markdown text to render.
        title: Brief title for the header.
        classification: Classification marking.
        plan_name: Optional plan name for the header.

    Returns:
        PDF file content as bytes.
    """
    html_str = _markdown_to_html(
        content_md,
        title=title,
        classification=classification,
        plan_name=plan_name,
    )

    pdf_bytes: bytes = HTML(string=html_str).write_pdf()
    logger.info("pdf_rendered title=%s size=%d", title, len(pdf_bytes))
    return pdf_bytes


def upload_pdf_to_minio(
    pdf_bytes: bytes,
    object_name: str,
    *,
    bucket: str = BRIEF_PDF_BUCKET,
) -> str:
    """Upload PDF bytes to MinIO and return the object URI.

    Args:
        pdf_bytes: PDF file content.
        object_name: Object key in the bucket (e.g. ``"briefs/<uuid>.pdf"``).
        bucket: MinIO bucket name.

    Returns:
        MinIO URI string in the form ``minio://<bucket>/<object_name>``.
    """
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )

    # Ensure the bucket exists.
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)

    data = io.BytesIO(pdf_bytes)
    client.put_object(
        bucket,
        object_name,
        data,
        length=len(pdf_bytes),
        content_type="application/pdf",
    )

    uri = f"minio://{bucket}/{object_name}"
    logger.info("pdf_uploaded uri=%s size=%d", uri, len(pdf_bytes))
    return uri


def generate_and_upload_pdf(
    brief_id: str,
    content_md: str,
    *,
    title: str = "",
    classification: str = "UNCLASSIFIED",
    plan_name: str = "",
) -> str:
    """Render a brief to PDF and upload to MinIO.

    This is the main entry point for PDF export. It renders the markdown
    to PDF, uploads to MinIO, and returns the URI.

    Args:
        brief_id: UUID of the brief (used for the object key).
        content_md: Markdown content to render.
        title: Brief title for the PDF header.
        classification: Classification marking.
        plan_name: Optional plan name for the PDF header.

    Returns:
        MinIO URI for the uploaded PDF.
    """
    pdf_bytes = render_brief_pdf(
        content_md,
        title=title,
        classification=classification,
        plan_name=plan_name,
    )

    object_name = f"briefs/{brief_id}.pdf"
    return upload_pdf_to_minio(pdf_bytes, object_name)
