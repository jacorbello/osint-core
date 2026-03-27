"""Tests for the university policy connector."""

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from osint_core.connectors.base import RawItem, SourceConfig
from osint_core.connectors.university_policy import UniversityPolicyConnector

SAMPLE_INDEX_PAGE = """<!DOCTYPE html>
<html>
<head><title>University Policies</title></head>
<body>
<h1>Policy Listing</h1>
<ul>
  <li><a class="policy-link" href="/policies/admissions.html">Admissions Policy</a></li>
  <li><a class="policy-link" href="/policies/tuition.pdf">Tuition Policy</a></li>
  <li><a class="policy-link" href="/policies/conduct.html">Student Conduct</a></li>
</ul>
</body>
</html>"""

SAMPLE_POLICY_HTML = """<!DOCTYPE html>
<html>
<head><title>Admissions Policy</title></head>
<body>
<h1>Admissions Policy</h1>
<p>All applicants must submit transcripts and test scores by the deadline.</p>
</body>
</html>"""

SAMPLE_POLICY_CHANGED = """<!DOCTYPE html>
<html>
<head><title>Admissions Policy</title></head>
<body>
<h1>Admissions Policy</h1>
<p>All applicants must submit transcripts by the deadline. Test scores are optional.</p>
</body>
</html>"""

SAMPLE_PDF_BYTES = b"%PDF-1.4 fake pdf content for testing"


@pytest.fixture()
def config() -> SourceConfig:
    return SourceConfig(
        id="test-university",
        type="university_policy",
        url="https://policy.example.edu",
        weight=0.5,
        extra={
            "institutions": [
                {
                    "name": "Example University",
                    "policy_url": "https://policy.example.edu/index.html",
                    "selector": "a.policy-link",
                },
            ],
            "archive_pdfs": False,
        },
    )


@pytest.fixture()
def connector(config: SourceConfig) -> UniversityPolicyConnector:
    return UniversityPolicyConnector(config)


@pytest.fixture(autouse=True)
def _mock_minio():
    """Prevent real MinIO connections in all tests."""
    mock_client = MagicMock()
    mock_client.bucket_exists.return_value = True
    with patch(
        "osint_core.connectors.university_policy.Minio",
        return_value=mock_client,
    ):
        yield mock_client


# --- Index page parsing ---


class TestExtractPolicyLinks:
    def test_extracts_links_matching_selector(self):
        links = UniversityPolicyConnector._extract_policy_links(
            SAMPLE_INDEX_PAGE,
            "https://policy.example.edu/index.html",
            "a.policy-link",
        )
        assert len(links) == 3

    def test_resolves_relative_urls(self):
        links = UniversityPolicyConnector._extract_policy_links(
            SAMPLE_INDEX_PAGE,
            "https://policy.example.edu/index.html",
            "a.policy-link",
        )
        urls = [url for _, url in links]
        assert "https://policy.example.edu/policies/admissions.html" in urls
        assert "https://policy.example.edu/policies/tuition.pdf" in urls

    def test_extracts_link_text_as_title(self):
        links = UniversityPolicyConnector._extract_policy_links(
            SAMPLE_INDEX_PAGE,
            "https://policy.example.edu/index.html",
            "a.policy-link",
        )
        titles = [title for title, _ in links]
        assert "Admissions Policy" in titles
        assert "Tuition Policy" in titles
        assert "Student Conduct" in titles

    def test_deduplicates_urls(self):
        html = """<html><body>
        <a class="policy-link" href="/policies/dup.html">Link A</a>
        <a class="policy-link" href="/policies/dup.html">Link B</a>
        </body></html>"""
        links = UniversityPolicyConnector._extract_policy_links(
            html, "https://example.edu/", "a.policy-link"
        )
        assert len(links) == 1

    def test_skips_tags_without_href(self):
        html = """<html><body>
        <a class="policy-link">No href</a>
        <a class="policy-link" href="/ok.html">Has href</a>
        </body></html>"""
        links = UniversityPolicyConnector._extract_policy_links(
            html, "https://example.edu/", "a.policy-link"
        )
        assert len(links) == 1

    def test_empty_page_returns_empty(self):
        links = UniversityPolicyConnector._extract_policy_links(
            "<html><body></body></html>",
            "https://example.edu/",
            "a.policy-link",
        )
        assert links == []


# --- Content hash diffing ---


class TestContentHashDiffing:
    @pytest.mark.asyncio
    async def test_new_policy_detected(self, connector, respx_mock):
        """First fetch of a policy produces a RawItem with change_type=new."""
        respx_mock.get("https://policy.example.edu/index.html").mock(
            return_value=httpx.Response(200, content=SAMPLE_INDEX_PAGE)
        )
        respx_mock.get("https://policy.example.edu/policies/admissions.html").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_POLICY_HTML,
                headers={"content-type": "text/html"},
            )
        )
        respx_mock.get("https://policy.example.edu/policies/tuition.pdf").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_PDF_BYTES,
                headers={"content-type": "application/pdf"},
            )
        )
        respx_mock.get("https://policy.example.edu/policies/conduct.html").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_POLICY_HTML,
                headers={"content-type": "text/html"},
            )
        )

        items = await connector.fetch()
        assert len(items) == 3
        assert all(item.raw_data["change_type"] == "new" for item in items)

    @pytest.mark.asyncio
    async def test_unchanged_policy_skipped(self, connector, respx_mock):
        """Second fetch of identical content produces no RawItem."""
        respx_mock.get("https://policy.example.edu/index.html").mock(
            return_value=httpx.Response(200, content=SAMPLE_INDEX_PAGE)
        )
        respx_mock.get("https://policy.example.edu/policies/admissions.html").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_POLICY_HTML,
                headers={"content-type": "text/html"},
            )
        )
        respx_mock.get("https://policy.example.edu/policies/tuition.pdf").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_PDF_BYTES,
                headers={"content-type": "application/pdf"},
            )
        )
        respx_mock.get("https://policy.example.edu/policies/conduct.html").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_POLICY_HTML,
                headers={"content-type": "text/html"},
            )
        )

        # First fetch — all new
        items_first = await connector.fetch()
        assert len(items_first) == 3

        # Second fetch — all unchanged
        items_second = await connector.fetch()
        assert len(items_second) == 0

    @pytest.mark.asyncio
    async def test_changed_policy_detected(self, connector, respx_mock):
        """Changed content on second fetch produces a RawItem with change_type=changed."""
        respx_mock.get("https://policy.example.edu/index.html").mock(
            return_value=httpx.Response(200, content=SAMPLE_INDEX_PAGE)
        )
        # First fetch returns original
        admissions_route = respx_mock.get(
            "https://policy.example.edu/policies/admissions.html"
        )
        admissions_route.side_effect = [
            httpx.Response(
                200, content=SAMPLE_POLICY_HTML, headers={"content-type": "text/html"}
            ),
            httpx.Response(
                200,
                content=SAMPLE_POLICY_CHANGED,
                headers={"content-type": "text/html"},
            ),
        ]
        respx_mock.get("https://policy.example.edu/policies/tuition.pdf").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_PDF_BYTES,
                headers={"content-type": "application/pdf"},
            )
        )
        respx_mock.get("https://policy.example.edu/policies/conduct.html").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_POLICY_HTML,
                headers={"content-type": "text/html"},
            )
        )

        # First fetch
        await connector.fetch()
        # Second fetch — admissions changed, others unchanged
        items = await connector.fetch()
        assert len(items) == 1
        assert items[0].raw_data["change_type"] == "changed"
        assert "Admissions" in items[0].title


# --- RawItem construction ---


class TestRawItemConstruction:
    @pytest.mark.asyncio
    async def test_rawitem_has_correct_fields(self, connector, respx_mock):
        """RawItem contains title, URL, summary, and policy metadata."""
        respx_mock.get("https://policy.example.edu/index.html").mock(
            return_value=httpx.Response(200, content=SAMPLE_INDEX_PAGE)
        )
        respx_mock.get("https://policy.example.edu/policies/admissions.html").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_POLICY_HTML,
                headers={"content-type": "text/html"},
            )
        )
        respx_mock.get("https://policy.example.edu/policies/tuition.pdf").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_PDF_BYTES,
                headers={"content-type": "application/pdf"},
            )
        )
        respx_mock.get("https://policy.example.edu/policies/conduct.html").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_POLICY_HTML,
                headers={"content-type": "text/html"},
            )
        )

        items = await connector.fetch()
        item = items[0]

        # Title includes institution name
        assert "[Example University]" in item.title
        # URL is absolute
        assert item.url.startswith("https://")
        # occurred_at is set
        assert item.occurred_at is not None
        # raw_data has required metadata
        assert "institution" in item.raw_data
        assert "document_type" in item.raw_data
        assert "content_hash" in item.raw_data
        assert "change_type" in item.raw_data

    @pytest.mark.asyncio
    async def test_html_policy_has_summary(self, connector, respx_mock):
        """HTML policy documents get a text summary extracted."""
        respx_mock.get("https://policy.example.edu/index.html").mock(
            return_value=httpx.Response(200, content=SAMPLE_INDEX_PAGE)
        )
        respx_mock.get("https://policy.example.edu/policies/admissions.html").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_POLICY_HTML,
                headers={"content-type": "text/html"},
            )
        )
        respx_mock.get("https://policy.example.edu/policies/tuition.pdf").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_PDF_BYTES,
                headers={"content-type": "application/pdf"},
            )
        )
        respx_mock.get("https://policy.example.edu/policies/conduct.html").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_POLICY_HTML,
                headers={"content-type": "text/html"},
            )
        )

        items = await connector.fetch()
        html_items = [i for i in items if i.raw_data["document_type"] == "html"]
        assert len(html_items) > 0
        assert "transcripts" in html_items[0].summary.lower()

    @pytest.mark.asyncio
    async def test_pdf_policy_has_empty_summary(self, connector, respx_mock):
        """PDF policy documents have an empty summary (no text extraction)."""
        respx_mock.get("https://policy.example.edu/index.html").mock(
            return_value=httpx.Response(200, content=SAMPLE_INDEX_PAGE)
        )
        respx_mock.get("https://policy.example.edu/policies/admissions.html").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_POLICY_HTML,
                headers={"content-type": "text/html"},
            )
        )
        respx_mock.get("https://policy.example.edu/policies/tuition.pdf").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_PDF_BYTES,
                headers={"content-type": "application/pdf"},
            )
        )
        respx_mock.get("https://policy.example.edu/policies/conduct.html").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_POLICY_HTML,
                headers={"content-type": "text/html"},
            )
        )

        items = await connector.fetch()
        pdf_items = [i for i in items if i.raw_data["document_type"] == "pdf"]
        assert len(pdf_items) == 1
        assert pdf_items[0].summary == ""


# --- Dedupe key ---


class TestDedupeKey:
    def test_dedupe_key_format(self, connector):
        item = RawItem(
            title="Test",
            url="https://example.edu/policy.html",
            raw_data={"content_hash": "abcdef1234567890abcdef"},
            summary="",
        )
        key = connector.dedupe_key(item)
        url_hash = hashlib.sha256(
            b"https://example.edu/policy.html"
        ).hexdigest()[:16]
        assert key == f"university_policy:test-university:{url_hash}:abcdef12"

    def test_dedupe_key_different_for_different_urls(self, connector):
        item_a = RawItem(
            title="A",
            url="https://example.edu/a.html",
            raw_data={"content_hash": "samehash"},
            summary="",
        )
        item_b = RawItem(
            title="B",
            url="https://example.edu/b.html",
            raw_data={"content_hash": "samehash"},
            summary="",
        )
        assert connector.dedupe_key(item_a) != connector.dedupe_key(item_b)

    def test_dedupe_key_different_for_different_content(self, connector):
        item_a = RawItem(
            title="A",
            url="https://example.edu/a.html",
            raw_data={"content_hash": "aaaa1111bbbb2222cccc3333"},
            summary="",
        )
        item_b = RawItem(
            title="A",
            url="https://example.edu/a.html",
            raw_data={"content_hash": "xxxx9999yyyy8888zzzz7777"},
            summary="",
        )
        assert connector.dedupe_key(item_a) != connector.dedupe_key(item_b)


# --- Retry logic ---


class TestRetryLogic:
    @pytest.mark.asyncio
    async def test_retries_on_503(self, connector, respx_mock):
        """Connector retries on 503 and succeeds on subsequent attempt."""
        index_route = respx_mock.get("https://policy.example.edu/index.html")
        index_route.side_effect = [
            httpx.Response(503),
            httpx.Response(200, content=SAMPLE_INDEX_PAGE),
        ]
        respx_mock.get("https://policy.example.edu/policies/admissions.html").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_POLICY_HTML,
                headers={"content-type": "text/html"},
            )
        )
        respx_mock.get("https://policy.example.edu/policies/tuition.pdf").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_PDF_BYTES,
                headers={"content-type": "application/pdf"},
            )
        )
        respx_mock.get("https://policy.example.edu/policies/conduct.html").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_POLICY_HTML,
                headers={"content-type": "text/html"},
            )
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            items = await connector.fetch()
        assert len(items) == 3

    @pytest.mark.asyncio
    async def test_returns_empty_after_max_retries(self, connector, respx_mock):
        """Connector returns empty list after exhausting retries."""
        respx_mock.get("https://policy.example.edu/index.html").mock(
            side_effect=[httpx.Response(503)] * 3
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            items = await connector.fetch()
        assert items == []

    @pytest.mark.asyncio
    async def test_retries_on_transport_error(self, connector, respx_mock):
        """Connector retries on transport errors."""
        index_route = respx_mock.get("https://policy.example.edu/index.html")
        index_route.side_effect = [
            httpx.ConnectError("connection refused"),
            httpx.Response(200, content=SAMPLE_INDEX_PAGE),
        ]
        respx_mock.get("https://policy.example.edu/policies/admissions.html").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_POLICY_HTML,
                headers={"content-type": "text/html"},
            )
        )
        respx_mock.get("https://policy.example.edu/policies/tuition.pdf").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_PDF_BYTES,
                headers={"content-type": "application/pdf"},
            )
        )
        respx_mock.get("https://policy.example.edu/policies/conduct.html").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_POLICY_HTML,
                headers={"content-type": "text/html"},
            )
        )

        with patch("asyncio.sleep", new_callable=AsyncMock):
            items = await connector.fetch()
        assert len(items) == 3

    @pytest.mark.asyncio
    async def test_returns_empty_on_404(self, connector, respx_mock):
        """Non-retryable error returns empty immediately."""
        respx_mock.get("https://policy.example.edu/index.html").mock(
            return_value=httpx.Response(404)
        )
        items = await connector.fetch()
        assert items == []


# --- MinIO archival ---


class TestMinIOArchival:
    @pytest.mark.asyncio
    async def test_archives_when_enabled(self, _mock_minio, respx_mock):
        """Policies are archived to MinIO when archive_pdfs is True."""
        config = SourceConfig(
            id="test-archive",
            type="university_policy",
            url="https://policy.example.edu",
            weight=0.5,
            extra={
                "institutions": [
                    {
                        "name": "Example University",
                        "policy_url": "https://policy.example.edu/index.html",
                        "selector": "a.policy-link",
                    },
                ],
                "archive_pdfs": True,
            },
        )
        conn = UniversityPolicyConnector(config)

        respx_mock.get("https://policy.example.edu/index.html").mock(
            return_value=httpx.Response(
                200,
                content='<html><body><a class="policy-link" href="/p.pdf">P</a></body></html>',
            )
        )
        respx_mock.get("https://policy.example.edu/p.pdf").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_PDF_BYTES,
                headers={"content-type": "application/pdf"},
            )
        )

        items = await conn.fetch()

        assert len(items) == 1
        assert items[0].raw_data.get("minio_uri") is not None
        assert items[0].raw_data.get("retention_class") == "evidentiary"
        _mock_minio.put_object.assert_called()

    @pytest.mark.asyncio
    async def test_skips_pdf_archive_when_disabled(self, connector, _mock_minio, respx_mock):
        """PDF archival is skipped when archive_pdfs is False."""
        respx_mock.get("https://policy.example.edu/index.html").mock(
            return_value=httpx.Response(
                200,
                content='<html><body><a class="policy-link" href="/p.pdf">P</a></body></html>',
            )
        )
        respx_mock.get("https://policy.example.edu/p.pdf").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_PDF_BYTES,
                headers={"content-type": "application/pdf"},
            )
        )

        items = await connector.fetch()

        # archive_pdfs is False so PDF should not be archived
        assert len(items) == 1
        assert items[0].raw_data.get("minio_uri") is None
