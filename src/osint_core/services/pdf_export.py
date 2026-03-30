"""PDF export service — render briefs to PDF and upload to MinIO."""

from __future__ import annotations

import io
import logging
from datetime import UTC, datetime
from html import escape

import markdown as markdown_lib
from minio import Minio, S3Error

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

    # Escape user-supplied values to prevent XSS/injection in the PDF.
    safe_title = escape(title) if title else "Intelligence Brief"
    safe_classification = escape(classification)
    safe_plan_name = escape(plan_name)

    header_parts = [f"<strong>{safe_classification}</strong>"]
    if safe_plan_name:
        header_parts.append(f"Plan: {safe_plan_name}")
    header_parts.append(f"Generated: {timestamp}")

    header_line = " &mdash; ".join(header_parts)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{safe_title}</title>
<style>
  @page {{
    size: A4;
    margin: 2cm;
    @top-center {{
      content: "{safe_classification}";
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

    from weasyprint import HTML  # lazy import — requires native libs (pango/cairo)

    # Disable URL fetching to prevent SSRF via embedded resources.
    pdf_bytes: bytes = HTML(
        string=html_str,
        url_fetcher=lambda url, **kw: {"string": "", "mime_type": "text/plain"},
    ).write_pdf()
    logger.info("pdf_rendered title=%s size=%d", title, len(pdf_bytes))
    return pdf_bytes


def upload_pdf_to_minio(
    pdf_bytes: bytes,
    object_name: str,
    *,
    bucket: str = BRIEF_PDF_BUCKET,
    retention_class: str = "standard",
) -> str:
    """Upload PDF bytes to MinIO and return the object URI.

    Args:
        pdf_bytes: PDF file content.
        object_name: Object key in the bucket (e.g. ``"briefs/<uuid>.pdf"``).
        bucket: MinIO bucket name.
        retention_class: Retention classification stored as object metadata
            (e.g. ``"standard"``, ``"evidentiary"``).

    Returns:
        MinIO URI string in the form ``minio://<bucket>/<object_name>``.
    """
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )

    # Ensure the bucket exists (handle race with concurrent requests).
    if not client.bucket_exists(bucket):
        try:
            client.make_bucket(bucket)
        except S3Error as exc:
            if exc.code != "BucketAlreadyOwnedByYou":
                raise

    metadata: dict[str, str | list[str] | tuple[str]] = {
        "retention-class": retention_class,
    }

    data = io.BytesIO(pdf_bytes)
    client.put_object(
        bucket,
        object_name,
        data,
        length=len(pdf_bytes),
        content_type="application/pdf",
        metadata=metadata,
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
    pdf_bytes: bytes | None = None,
) -> str:
    """Render a brief to PDF and upload to MinIO.

    Args:
        brief_id: UUID of the brief (used for the object key).
        content_md: Markdown content to render.
        title: Brief title for the PDF header.
        classification: Classification marking.
        plan_name: Optional plan name for the PDF header.
        pdf_bytes: Pre-rendered PDF bytes. If provided, skips rendering.

    Returns:
        MinIO URI for the uploaded PDF.
    """
    if pdf_bytes is None:
        pdf_bytes = render_brief_pdf(
            content_md,
            title=title,
            classification=classification,
            plan_name=plan_name,
        )

    object_name = f"briefs/{brief_id}.pdf"
    return upload_pdf_to_minio(pdf_bytes, object_name)
