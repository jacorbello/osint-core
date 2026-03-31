"""Tests for the university policy connector."""

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from osint_core.connectors.base import RawItem, SourceConfig
from osint_core.connectors.university_policy import UniversityPolicyConnector


class FakeRedisHash:
    """In-memory dict that mimics async Redis HSET/HGET for testing."""

    def __init__(self):
        self._data: dict[str, dict[str, str]] = {}
        self.closed: bool = False

    async def hget(self, name: str, key: str) -> str | None:
        return self._data.get(name, {}).get(key)

    async def hset(self, name: str, key: str, value: str) -> int:
        self._data.setdefault(name, {})[key] = value
        return 1

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        self.closed = True

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
def fake_redis() -> FakeRedisHash:
    """Shared fake Redis instance that persists across connector instances."""
    return FakeRedisHash()


@pytest.fixture(autouse=True)
def _mock_redis(fake_redis):
    """Prevent real Redis connections; inject fake Redis for all tests."""
    with patch(
        "redis.asyncio.from_url",
        return_value=fake_redis,
    ):
        yield fake_redis


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

    @pytest.mark.asyncio
    async def test_redirect_to_internal_host_blocked(self, respx_mock):
        """Redirects from allowed domains to internal hosts are blocked."""
        config = SourceConfig(
            id="test-redirect-internal",
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

        # Index page links to a document on an allowed domain
        index_html = """<html><body>
        <a class="policy-link" href="https://policy.example.edu/redirect-me.html">Doc</a>
        </body></html>"""

        respx_mock.get("https://policy.example.edu/index.html").mock(
            return_value=httpx.Response(200, content=index_html)
        )

        # Allowed URL responds with a redirect to an internal host
        respx_mock.get("https://policy.example.edu/redirect-me.html").mock(
            return_value=httpx.Response(
                302,
                headers={"Location": "http://localhost:9000/secret"},
            )
        )

        # The connector should reject the redirect target and return no items
        items = await connector.fetch()
        assert len(items) == 0

    @pytest.mark.asyncio
    async def test_redirect_to_allowed_domain_succeeds(self, respx_mock):
        """Redirects from allowed domains to other allowed domains succeed."""
        config = SourceConfig(
            id="test-redirect-ok",
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

        index_html = """<html><body>
        <a class="policy-link" href="https://policy.example.edu/old.html">Doc</a>
        </body></html>"""

        respx_mock.get("https://policy.example.edu/index.html").mock(
            return_value=httpx.Response(200, content=index_html)
        )

        # Redirect to another allowed .edu domain
        respx_mock.get("https://policy.example.edu/old.html").mock(
            return_value=httpx.Response(
                301,
                headers={"Location": "https://new-policy.example.edu/doc.html"},
            )
        )
        respx_mock.get("https://new-policy.example.edu/doc.html").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_POLICY_HTML,
                headers={"content-type": "text/html"},
            )
        )

        items = await connector.fetch()
        assert len(items) == 1

    def test_string_suffix_raises_type_error(self):
        """Passing a bare string for allowed_domain_suffixes raises TypeError."""
        config = SourceConfig(
            id="test-string-suffix",
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
                "allowed_domain_suffixes": ".gov",
            },
        )
        with pytest.raises(TypeError, match="not a single string"):
            UniversityPolicyConnector(config)

    def test_non_string_suffix_element_raises_type_error(self):
        """Non-string elements in allowed_domain_suffixes raises TypeError."""
        config = SourceConfig(
            id="test-bad-suffix",
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
                "allowed_domain_suffixes": [".edu", 123],
            },
        )
        with pytest.raises(TypeError, match="must all be strings"):
            UniversityPolicyConnector(config)

    def test_link_local_ip_rejected(self):
        """Link-local IP (169.254.x.x) is rejected at init."""
        config = SourceConfig(
            id="test-link-local",
            type="university_policy",
            url="https://policy.example.edu",
            weight=0.5,
            extra={
                "institutions": [
                    {
                        "name": "Link Local",
                        "policy_url": "http://169.254.169.254/metadata",
                        "selector": "a.policy-link",
                    },
                ],
            },
        )
        with pytest.raises(ValueError, match="Link Local"):
            UniversityPolicyConnector(config)

    def test_zero_ip_rejected(self):
        """Unspecified IP (0.0.0.0) is rejected at init."""
        config = SourceConfig(
            id="test-zero",
            type="university_policy",
            url="https://policy.example.edu",
            weight=0.5,
            extra={
                "institutions": [
                    {
                        "name": "Zero IP",
                        "policy_url": "http://0.0.0.0/admin",
                        "selector": "a.policy-link",
                    },
                ],
            },
        )
        with pytest.raises(ValueError, match="Zero IP"):
            UniversityPolicyConnector(config)


# --- Redis hash persistence ---


class TestRedisPersistence:
    """Verify content hashes persist across connector instances via Redis."""

    @pytest.mark.asyncio
    async def test_hash_persists_across_instances(self, config, fake_redis, respx_mock):
        """Hash stored by one connector instance is visible to a new instance."""
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

        # First connector instance: all policies are new
        conn1 = UniversityPolicyConnector(config)
        items1 = await conn1.fetch()
        assert len(items1) == 3

        # Second connector instance (simulates worker restart) with same Redis
        conn2 = UniversityPolicyConnector(config)
        items2 = await conn2.fetch()
        assert len(items2) == 0, "Unchanged docs should be skipped after restart"

    @pytest.mark.asyncio
    async def test_unchanged_doc_detected_after_reinstantiation(
        self, config, fake_redis, respx_mock
    ):
        """A specific document is recognized as unchanged by a new instance."""
        respx_mock.get("https://policy.example.edu/index.html").mock(
            return_value=httpx.Response(
                200,
                content=(
                    '<html><body>'
                    '<a class="policy-link" href="/policies/single.html">Single</a>'
                    '</body></html>'
                ),
            )
        )
        respx_mock.get("https://policy.example.edu/policies/single.html").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_POLICY_HTML,
                headers={"content-type": "text/html"},
            )
        )

        # First instance processes the document
        conn1 = UniversityPolicyConnector(config)
        items1 = await conn1.fetch()
        assert len(items1) == 1
        assert items1[0].raw_data["change_type"] == "new"

        # New instance sees same content as unchanged
        conn2 = UniversityPolicyConnector(config)
        items2 = await conn2.fetch()
        assert len(items2) == 0

    @pytest.mark.asyncio
    async def test_hash_key_uses_source_id(self, fake_redis, respx_mock):
        """Redis hash key incorporates source_id for namespace isolation."""
        config_a = SourceConfig(
            id="source-a",
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
        config_b = SourceConfig(
            id="source-b",
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
        conn_a = UniversityPolicyConnector(config_a)
        conn_b = UniversityPolicyConnector(config_b)
        assert conn_a._redis_hash_key == "policy_hashes:source-a"
        assert conn_b._redis_hash_key == "policy_hashes:source-b"
        assert conn_a._redis_hash_key != conn_b._redis_hash_key

    @pytest.mark.asyncio
    async def test_fallback_to_memory_when_redis_unavailable(
        self, config, respx_mock
    ):
        """Connector falls back to in-memory hashes when Redis is down."""
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

        conn = UniversityPolicyConnector(config)
        # Simulate Redis being unavailable
        conn._redis_available = False

        items1 = await conn.fetch()
        assert len(items1) == 3

        # Same instance still uses fallback dict
        items2 = await conn.fetch()
        assert len(items2) == 0

    @pytest.mark.asyncio
    async def test_redis_closed_after_fetch(self, config, fake_redis, respx_mock):
        """Redis client is closed at the end of fetch() to prevent connection leaks."""
        respx_mock.get("https://policy.example.edu/index.html").mock(
            return_value=httpx.Response(
                200,
                content=(
                    '<html><body>'
                    '<a class="policy-link" href="/policies/single.html">Single</a>'
                    '</body></html>'
                ),
            )
        )
        respx_mock.get("https://policy.example.edu/policies/single.html").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_POLICY_HTML,
                headers={"content-type": "text/html"},
            )
        )

        conn = UniversityPolicyConnector(config)
        await conn.fetch()

        # After fetch completes, the Redis client should be cleaned up
        assert conn._redis is None
        assert fake_redis.closed is True

    @pytest.mark.asyncio
    async def test_redis_read_error_triggers_fallback(self, config, respx_mock):
        """A Redis read error disables Redis and switches to in-memory fallback."""
        failing_redis = FakeRedisHash()

        async def _hget_fail(name, key):
            import redis.exceptions

            raise redis.exceptions.RedisError("read failure")

        failing_redis.hget = _hget_fail

        with patch("redis.asyncio.from_url", return_value=failing_redis):
            conn = UniversityPolicyConnector(config)

            respx_mock.get("https://policy.example.edu/index.html").mock(
                return_value=httpx.Response(
                    200,
                    content=(
                        '<html><body>'
                        '<a class="policy-link" href="/policies/single.html">Single</a>'
                        '</body></html>'
                    ),
                )
            )
            respx_mock.get("https://policy.example.edu/policies/single.html").mock(
                return_value=httpx.Response(
                    200,
                    content=SAMPLE_POLICY_HTML,
                    headers={"content-type": "text/html"},
                )
            )

            items = await conn.fetch()
            assert len(items) == 1
            # Redis should be marked unavailable after the read error
            assert conn._redis_available is False

    @pytest.mark.asyncio
    async def test_redis_write_error_triggers_fallback(self, config, respx_mock):
        """A Redis write error disables Redis and stores hash in memory."""
        failing_redis = FakeRedisHash()

        async def _hset_fail(name, key, value):
            import redis.exceptions

            raise redis.exceptions.RedisError("write failure")

        failing_redis.hset = _hset_fail

        with patch("redis.asyncio.from_url", return_value=failing_redis):
            conn = UniversityPolicyConnector(config)

            respx_mock.get("https://policy.example.edu/index.html").mock(
                return_value=httpx.Response(
                    200,
                    content=(
                        '<html><body>'
                        '<a class="policy-link" href="/policies/single.html">Single</a>'
                        '</body></html>'
                    ),
                )
            )
            respx_mock.get("https://policy.example.edu/policies/single.html").mock(
                return_value=httpx.Response(
                    200,
                    content=SAMPLE_POLICY_HTML,
                    headers={"content-type": "text/html"},
                )
            )

            items = await conn.fetch()
            assert len(items) == 1
            # Redis should be marked unavailable after the write error
            assert conn._redis_available is False
            # The hash should have been stored in the fallback dict
            assert len(conn._fallback_hashes) == 1

    @pytest.mark.asyncio
    async def test_fallback_hashes_not_populated_when_redis_healthy(
        self, config, fake_redis, respx_mock
    ):
        """When Redis is healthy, _fallback_hashes stays empty."""
        respx_mock.get("https://policy.example.edu/index.html").mock(
            return_value=httpx.Response(
                200,
                content=(
                    '<html><body>'
                    '<a class="policy-link" href="/policies/single.html">Single</a>'
                    '</body></html>'
                ),
            )
        )
        respx_mock.get("https://policy.example.edu/policies/single.html").mock(
            return_value=httpx.Response(
                200,
                content=SAMPLE_POLICY_HTML,
                headers={"content-type": "text/html"},
            )
        )

        conn = UniversityPolicyConnector(config)
        await conn.fetch()

        # Hash should be in Redis, not in the fallback dict
        assert len(conn._fallback_hashes) == 0
        assert len(fake_redis._data.get("policy_hashes:test-university", {})) == 1


class TestUpdatedSelectors:
    """Verify updated CSS selectors match actual institution HTML (#213)."""

    @staticmethod
    def _extract(html: str, selector: str, base_url: str) -> list[tuple[str, str]]:
        return UniversityPolicyConnector._extract_policy_links(html, base_url, selector)

    def test_uc_system_selector(self):
        """UC System browse page uses a.blue links to /doc/NNN."""
        html = """
        <div id="content">
          <div><a class="blue" href="/doc/4000701">View PolicyAbusive Conduct</a></div>
          <div><a class="blue" href="/doc/1001004">View PolicyAnti-Discrimination</a></div>
          <a href="?action=search">Search policies</a>
        </div>
        """
        links = self._extract(html, "a.blue[href*='/doc/']", "https://policy.ucop.edu")
        assert len(links) == 2
        assert links[0] == ("View PolicyAbusive Conduct", "https://policy.ucop.edu/doc/4000701")

    def test_tamu_system_selector(self):
        """TAMU policy library page uses direct PDF links."""
        html = """
        <main>
          <a href="https://policies.tamus.edu/01-01.pdf">01.01</a>
          <a href="https://policies.tamus.edu/02-01.pdf">02.01</a>
          <a href="https://www.tamus.edu/legal/policy/">Policy Office</a>
        </main>
        """
        links = self._extract(
            html, "a[href$='.pdf']",
            "https://policies.tamus.edu",
        )
        assert len(links) == 2
        assert links[0][1] == "https://policies.tamus.edu/01-01.pdf"

    def test_udc_selector(self):
        """UDC OGC policies page links to docs.udc.edu PDFs."""
        html = """
        <main>
          <li><a href="https://docs.udc.edu/ogc/Minors.pdf">
            Protection of Minors</a></li>
          <li><a href="https://docs.udc.edu/ogc/Form.docx">
            Mandatory Reporter Form</a></li>
          <li><a href="https://www.udc.edu/about">About UDC</a></li>
        </main>
        """
        links = self._extract(
            html, "a[href$='.pdf']",
            "https://www.udc.edu/about/administration/ogc/policies",
        )
        assert len(links) == 1
        assert links[0][1] == "https://docs.udc.edu/ogc/Minors.pdf"

    def test_csu_selector(self):
        """CSU board meetings page has meeting links and PDFs."""
        html = """
        <main>
          <a href="/csu-system/board-of-trustees/past-meetings/2026/Pages/March.aspx">
            March 2026</a>
          <a href="/csu-system/board-of-trustees/past-meetings/2025/Pages/Nov.aspx">
            November 2025</a>
          <a href="/csu-system/board-of-trustees/PastNotices/Documents/notice.pdf">
            Meeting Notice</a>
          <a href="/about">About CSU</a>
        </main>
        """
        links = self._extract(
            html, "a[href*='past-meetings/'], a[href$='.pdf']",
            "https://www.calstate.edu/csu-system/board-of-trustees/past-meetings",
        )
        assert len(links) == 3
        assert "March" in links[0][0]


class TestImpersonationFetch:
    """Tests for curl_cffi browser impersonation (#220)."""

    @pytest.mark.asyncio()
    async def test_impersonation_used_when_configured(self):
        """Institution with impersonate='true' uses curl_cffi."""
        config = SourceConfig(
            id="test-impersonate",
            type="university_policy",
            url="https://policy.example.edu",
            weight=0.5,
            extra={
                "institutions": [{
                    "name": "Bot-Protected University",
                    "policy_url": "https://botcheck.example.edu/policies",
                    "selector": "a[href$='.pdf']",
                    "impersonate": "true",
                }],
            },
        )
        connector = UniversityPolicyConnector(config)

        mock_cffi_resp = MagicMock()
        mock_cffi_resp.status_code = 200
        mock_cffi_resp.content = b"<html><a href='/doc.pdf'>Policy</a></html>"
        mock_cffi_resp.headers = {"content-type": "text/html"}

        async def fake_to_thread(fn, *args, **kwargs):
            return mock_cffi_resp

        with patch(
            "osint_core.connectors.university_policy.asyncio.to_thread",
            side_effect=fake_to_thread,
        ):
            resp = await connector._fetch_with_impersonation(
                "https://botcheck.example.edu/policies",
            )

        assert resp is not None
        assert resp.status_code == 200

    @pytest.mark.asyncio()
    async def test_impersonation_returns_none_without_curl_cffi(self):
        """Gracefully returns None when curl_cffi is not installed."""
        config = SourceConfig(
            id="test-no-cffi",
            type="university_policy",
            url="https://policy.example.edu",
            weight=0.5,
            extra={
                "institutions": [{
                    "name": "Test University",
                    "policy_url": "https://test.example.edu",
                    "selector": "a",
                }],
            },
        )
        connector = UniversityPolicyConnector(config)

        with patch(
            "osint_core.connectors.university_policy.cffi_requests", None,
        ):
            resp = await connector._fetch_with_impersonation(
                "https://test.example.edu",
            )

        assert resp is None
