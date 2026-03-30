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


# --- CSS selector validation ---


class TestCSSSelectorValidation:
    def test_valid_selectors_pass_validation(self):
        """Valid CSS selectors are accepted without error."""
        config = SourceConfig(
            id="test-valid",
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
            },
        )
        # Should not raise
        connector = UniversityPolicyConnector(config)
        assert connector is not None

    def test_valid_compound_selector_passes(self):
        """Compound selectors (comma-separated) are accepted."""
        config = SourceConfig(
            id="test-compound",
            type="university_policy",
            url="https://policy.example.edu",
            weight=0.5,
            extra={
                "institutions": [
                    {
                        "name": "Example University",
                        "policy_url": "https://policy.example.edu/index.html",
                        "selector": "a[href$='.pdf'], a[href*='policy']",
                    },
                ],
            },
        )
        connector = UniversityPolicyConnector(config)
        assert connector is not None

    def test_malformed_selector_raises_value_error(self):
        """Malformed CSS selector raises ValueError at init with institution name."""
        config = SourceConfig(
            id="test-bad",
            type="university_policy",
            url="https://policy.example.edu",
            weight=0.5,
            extra={
                "institutions": [
                    {
                        "name": "Bad University",
                        "policy_url": "https://policy.example.edu/index.html",
                        "selector": "a[href$=",
                    },
                ],
            },
        )
        with pytest.raises(ValueError, match="Bad University"):
            UniversityPolicyConnector(config)

    def test_malformed_selector_includes_selector_value(self):
        """Error message includes the malformed selector value."""
        config = SourceConfig(
            id="test-bad2",
            type="university_policy",
            url="https://policy.example.edu",
            weight=0.5,
            extra={
                "institutions": [
                    {
                        "name": "Another University",
                        "policy_url": "https://policy.example.edu/index.html",
                        "selector": "###invalid",
                    },
                ],
            },
        )
        with pytest.raises(ValueError, match="###invalid"):
            UniversityPolicyConnector(config)

    def test_multiple_institutions_all_validated(self):
        """All institution selectors are validated; error on second bad one."""
        config = SourceConfig(
            id="test-multi",
            type="university_policy",
            url="https://policy.example.edu",
            weight=0.5,
            extra={
                "institutions": [
                    {
                        "name": "Good University",
                        "policy_url": "https://example.edu",
                        "selector": "a.policy-link",
                    },
                    {
                        "name": "Broken University",
                        "policy_url": "https://example.edu",
                        "selector": "[[[",
                    },
                ],
            },
        )
        with pytest.raises(ValueError, match="Broken University"):
            UniversityPolicyConnector(config)

    def test_default_institutions_have_valid_selectors(self):
        """All default institution selectors pass validation."""
        config = SourceConfig(
            id="test-defaults",
            type="university_policy",
            url="https://policy.example.edu",
            weight=0.5,
            extra=None,
        )
        # Should not raise — default selectors are all valid
        connector = UniversityPolicyConnector(config)
        assert connector is not None


# --- Domain allowlist validation ---


class TestDomainAllowlistValidation:
    """URL domain validation against allowlist (SSRF mitigation)."""

    def test_valid_edu_url_accepted(self):
        """A .edu policy URL is accepted by default allowlist."""
        config = SourceConfig(
            id="test-edu",
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
            },
        )
        connector = UniversityPolicyConnector(config)
        assert connector is not None

    def test_localhost_rejected_at_init(self):
        """Internal URL (localhost) is rejected at init."""
        config = SourceConfig(
            id="test-localhost",
            type="university_policy",
            url="https://policy.example.edu",
            weight=0.5,
            extra={
                "institutions": [
                    {
                        "name": "Bad Institution",
                        "policy_url": "http://localhost:9000/internal",
                        "selector": "a.policy-link",
                    },
                ],
            },
        )
        with pytest.raises(ValueError, match="Bad Institution"):
            UniversityPolicyConnector(config)

    def test_private_ip_10_rejected_at_init(self):
        """Internal URL (10.x.x.x) is rejected at init."""
        config = SourceConfig(
            id="test-private-10",
            type="university_policy",
            url="https://policy.example.edu",
            weight=0.5,
            extra={
                "institutions": [
                    {
                        "name": "Private Net",
                        "policy_url": "http://10.0.0.1:8080/admin",
                        "selector": "a.policy-link",
                    },
                ],
            },
        )
        with pytest.raises(ValueError, match="Private Net"):
            UniversityPolicyConnector(config)

    def test_private_ip_127_rejected_at_init(self):
        """Loopback IP (127.0.0.1) is rejected at init."""
        config = SourceConfig(
            id="test-loopback",
            type="university_policy",
            url="https://policy.example.edu",
            weight=0.5,
            extra={
                "institutions": [
                    {
                        "name": "Loopback",
                        "policy_url": "http://127.0.0.1:5432/db",
                        "selector": "a.policy-link",
                    },
                ],
            },
        )
        with pytest.raises(ValueError, match="Loopback"):
            UniversityPolicyConnector(config)

    def test_private_ip_192_168_rejected_at_init(self):
        """Private IP (192.168.x.x) is rejected at init."""
        config = SourceConfig(
            id="test-192",
            type="university_policy",
            url="https://policy.example.edu",
            weight=0.5,
            extra={
                "institutions": [
                    {
                        "name": "Home Net",
                        "policy_url": "http://192.168.1.1/config",
                        "selector": "a.policy-link",
                    },
                ],
            },
        )
        with pytest.raises(ValueError, match="Home Net"):
            UniversityPolicyConnector(config)

    def test_private_ip_172_16_rejected_at_init(self):
        """Private IP (172.16.x.x) is rejected at init."""
        config = SourceConfig(
            id="test-172",
            type="university_policy",
            url="https://policy.example.edu",
            weight=0.5,
            extra={
                "institutions": [
                    {
                        "name": "Docker Net",
                        "policy_url": "http://172.16.0.1/service",
                        "selector": "a.policy-link",
                    },
                ],
            },
        )
        with pytest.raises(ValueError, match="Docker Net"):
            UniversityPolicyConnector(config)

    def test_non_edu_url_rejected_without_custom_allowlist(self):
        """Non-.edu URL is rejected unless in custom allowlist."""
        config = SourceConfig(
            id="test-non-edu",
            type="university_policy",
            url="https://policy.example.edu",
            weight=0.5,
            extra={
                "institutions": [
                    {
                        "name": "Evil Corp",
                        "policy_url": "https://evil.example.com/policies",
                        "selector": "a.policy-link",
                    },
                ],
            },
        )
        with pytest.raises(ValueError, match="Evil Corp"):
            UniversityPolicyConnector(config)

    def test_non_edu_url_accepted_with_custom_allowlist(self):
        """Non-.edu URL is accepted if in custom allowed_domains."""
        config = SourceConfig(
            id="test-custom",
            type="university_policy",
            url="https://policy.example.edu",
            weight=0.5,
            extra={
                "institutions": [
                    {
                        "name": "Gov Institution",
                        "policy_url": "https://policies.state.gov/index.html",
                        "selector": "a.policy-link",
                    },
                ],
                "allowed_domains": ["policies.state.gov"],
            },
        )
        connector = UniversityPolicyConnector(config)
        assert connector is not None

    def test_custom_domain_suffix_accepted(self):
        """Custom allowed_domain_suffixes extend the default .edu suffix."""
        config = SourceConfig(
            id="test-suffix",
            type="university_policy",
            url="https://policy.example.edu",
            weight=0.5,
            extra={
                "institutions": [
                    {
                        "name": "Gov Institution",
                        "policy_url": "https://policies.example.gov/index.html",
                        "selector": "a.policy-link",
                    },
                ],
                "allowed_domain_suffixes": [".edu", ".gov"],
            },
        )
        connector = UniversityPolicyConnector(config)
        assert connector is not None

    def test_default_institutions_have_valid_urls(self):
        """All default institution URLs pass domain validation."""
        config = SourceConfig(
            id="test-defaults-urls",
            type="university_policy",
            url="https://policy.example.edu",
            weight=0.5,
            extra=None,
        )
        connector = UniversityPolicyConnector(config)
        assert connector is not None

    def test_error_message_includes_url(self):
        """Error message includes the rejected URL."""
        config = SourceConfig(
            id="test-msg",
            type="university_policy",
            url="https://policy.example.edu",
            weight=0.5,
            extra={
                "institutions": [
                    {
                        "name": "Bad Place",
                        "policy_url": "http://internal-db:5432/dump",
                        "selector": "a.policy-link",
                    },
                ],
            },
        )
        with pytest.raises(ValueError, match="internal-db:5432"):
            UniversityPolicyConnector(config)

    @pytest.mark.asyncio
    async def test_extracted_url_rejected_at_fetch(self, respx_mock):
        """Extracted document URLs are validated before fetch."""
        config = SourceConfig(
            id="test-extract",
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
            },
        )
        connector = UniversityPolicyConnector(config)

        # Index page contains a link to an internal URL
        malicious_index = """<html><body>
        <a class="policy-link" href="http://localhost:9000/secret">Secret</a>
        <a class="policy-link" href="https://policy.example.edu/ok.html">OK</a>
        </body></html>"""

        respx_mock.get("https://policy.example.edu/index.html").mock(
            return_value=httpx.Response(200, content=malicious_index)
        )
        respx_mock.get("https://policy.example.edu/ok.html").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_POLICY_HTML,
                headers={"content-type": "text/html"},
            )
        )

        items = await connector.fetch()
        # Only the allowed URL should produce a RawItem
        assert len(items) == 1
        assert "ok.html" in items[0].url
