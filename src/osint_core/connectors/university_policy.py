"""University policy portal connector.

Scrapes state university policy portals, detects new/changed policies via
content-hash diffing, downloads documents (HTML or PDF), archives them as
Artifacts in MinIO, and produces one RawItem per new or changed policy.
"""

import asyncio
import contextlib
import hashlib
import io
import ipaddress
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
import soupsieve
import structlog
from bs4 import BeautifulSoup
from minio import Minio, S3Error

from osint_core.config import settings
from osint_core.connectors.base import BaseConnector, RawItem

logger = structlog.get_logger()

_MAX_RETRIES = 3
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
_ARTIFACT_BUCKET = "osint-artifacts"

# Default trusted domain suffixes for URL validation (SSRF mitigation)
_DEFAULT_ALLOWED_DOMAIN_SUFFIXES: tuple[str, ...] = (".edu",)

# Private/internal network patterns that must always be rejected
_PRIVATE_HOSTNAMES = {"localhost", "localhost.localdomain"}

# Default institution configurations
DEFAULT_INSTITUTIONS: list[dict[str, str]] = [
    {
        "name": "University of California System",
        "policy_url": "https://policy.ucop.edu/advanced-search.php",
        "selector": "a.policy-link, table.policies a[href*='doc']",
    },
    {
        "name": "California State University System",
        "policy_url": "https://www.calstate.edu/csu-system/board-of-trustees/past-meetings",
        "selector": "a[href$='.pdf'], a[href*='policy']",
    },
    {
        "name": "University of Texas System",
        "policy_url": "https://www.utsystem.edu/offices/board-regents/regents-rules-and-regulations",
        "selector": "a[href$='.pdf'], a[href*='rule'], a[href*='policy']",
    },
    {
        "name": "Texas A&M University System",
        "policy_url": "https://policies.tamus.edu",
        "selector": "a[href*='policy'], a[href*='regulation']",
    },
    {
        "name": "University of Minnesota",
        "policy_url": "https://policy.umn.edu/policies",
        "selector": "a[href*='policy']",
    },
    {
        "name": "University of the District of Columbia",
        "policy_url": "https://www.udc.edu/policies/",
        "selector": "a[href$='.pdf'], a[href*='policy']",
    },
]


class UniversityPolicyConnector(BaseConnector):
    """Fetches university policy portals and detects new/changed policies."""

    def __init__(self, config: Any) -> None:
        super().__init__(config)
        extra = config.extra or {}
        self._institutions: list[dict[str, str]] = extra.get(
            "institutions", DEFAULT_INSTITUTIONS
        )
        self._allowed_domain_suffixes: tuple[str, ...] = tuple(
            extra.get("allowed_domain_suffixes", _DEFAULT_ALLOWED_DOMAIN_SUFFIXES)
        )
        self._allowed_domains: frozenset[str] = frozenset(
            extra.get("allowed_domains", ())
        )
        self._validate_selectors()
        self._validate_urls()
        self._archive_pdfs: bool = extra.get("archive_pdfs", True)
        # In-memory hash store; a production deployment would persist this.
        self._known_hashes: dict[str, str] = {}

    def _validate_selectors(self) -> None:
        """Validate CSS selectors for all institutions at init time.

        Raises ``ValueError`` with the institution name and malformed selector
        so configuration errors surface immediately rather than mid-scrape.
        """
        for institution in self._institutions:
            name = institution.get("name", "<unknown>")
            selector = institution.get("selector", "")
            try:
                soupsieve.compile(selector)
            except soupsieve.SelectorSyntaxError as exc:
                msg = (
                    f"Invalid CSS selector for institution {name!r}: "
                    f"{selector!r} — {exc}"
                )
                raise ValueError(msg) from exc

    def _validate_urls(self) -> None:
        """Validate policy URLs for all institutions against the domain allowlist.

        Rejects URLs pointing to internal/private addresses (SSRF mitigation)
        and URLs whose domain does not match the allowlist.

        Raises ``ValueError`` with the institution name and rejected URL.
        """
        for institution in self._institutions:
            name = institution.get("name", "<unknown>")
            url = institution.get("policy_url", "")
            if not self._is_url_allowed(url):
                msg = (
                    f"Disallowed URL for institution {name!r}: "
                    f"{url!r} — domain not in allowlist"
                )
                raise ValueError(msg)

    def _is_url_allowed(self, url: str) -> bool:
        """Check whether a URL's domain is in the allowlist.

        Returns ``False`` for:
        - Private/internal hostnames (localhost, etc.)
        - Private/reserved IP addresses (127.x, 10.x, 172.16-31.x, 192.168.x, etc.)
        - Domains not matching any allowed suffix or explicit allowed domain
        """
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()

        if not hostname:
            return False

        # Reject private hostnames
        if hostname in _PRIVATE_HOSTNAMES:
            return False

        # Reject private/reserved IP addresses
        try:
            addr = ipaddress.ip_address(hostname)
            if addr.is_private or addr.is_loopback or addr.is_reserved:
                return False
        except ValueError:
            pass  # Not an IP address — proceed with domain checks

        # Check explicit allowed domains
        if hostname in self._allowed_domains:
            return True

        # Check allowed domain suffixes
        return any(hostname.endswith(suffix) for suffix in self._allowed_domain_suffixes)

    async def fetch(self) -> list[RawItem]:
        items: list[RawItem] = []
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            for institution in self._institutions:
                inst_items = await self._fetch_institution(client, institution)
                items.extend(inst_items)
        return items

    # ------------------------------------------------------------------
    # Institution-level fetching
    # ------------------------------------------------------------------

    async def _fetch_institution(
        self,
        client: httpx.AsyncClient,
        institution: dict[str, str],
    ) -> list[RawItem]:
        """Fetch the policy index page for one institution and process links."""
        name = institution["name"]
        policy_url = institution["policy_url"]
        selector = institution["selector"]

        logger.info(
            "university_policy_fetch_start",
            source_id=self.config.id,
            institution=name,
            url=policy_url,
        )

        resp = await self._fetch_with_retries(client, policy_url)
        if resp is None:
            return []

        links = self._extract_policy_links(resp.text, policy_url, selector)
        logger.info(
            "university_policy_links_found",
            source_id=self.config.id,
            institution=name,
            count=len(links),
        )

        items: list[RawItem] = []
        for title, url in links:
            item = await self._process_policy(client, institution, title, url)
            if item is not None:
                items.append(item)
        return items

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _fetch_with_retries(
        self,
        client: httpx.AsyncClient,
        url: str,
    ) -> httpx.Response | None:
        """Fetch a URL with retry logic for transient HTTP errors."""
        for attempt in range(_MAX_RETRIES):
            try:
                resp = await client.get(url)
            except httpx.TransportError as exc:
                logger.warning(
                    "university_policy_transport_error",
                    source_id=self.config.id,
                    url=url,
                    error=str(exc),
                    attempt=attempt + 1,
                )
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(2**attempt)
                continue

            if resp.status_code in _RETRYABLE_STATUS_CODES:
                raw_retry = resp.headers.get("Retry-After")
                if raw_retry is not None:
                    try:
                        delay = min(int(raw_retry), 60)
                    except (ValueError, TypeError):
                        delay = 2**attempt
                else:
                    delay = 2**attempt
                logger.warning(
                    "university_policy_retryable_http_error",
                    source_id=self.config.id,
                    url=url,
                    status=resp.status_code,
                    retry_after=delay,
                    attempt=attempt + 1,
                )
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(delay)
                continue

            if resp.is_error:
                logger.error(
                    "university_policy_http_error",
                    source_id=self.config.id,
                    url=url,
                    status=resp.status_code,
                )
                return None

            return resp

        logger.error(
            "university_policy_max_retries_exceeded",
            source_id=self.config.id,
            url=url,
            attempts=_MAX_RETRIES,
        )
        return None

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_policy_links(
        html: str,
        base_url: str,
        selector: str,
    ) -> list[tuple[str, str]]:
        """Parse an index page and return (title, absolute_url) pairs."""
        soup = BeautifulSoup(html, "html.parser")
        links: list[tuple[str, str]] = []
        seen_urls: set[str] = set()

        for tag in soup.select(selector):
            href = tag.get("href")
            if not href or not isinstance(href, str):
                continue
            abs_url = urljoin(base_url, href)
            if abs_url in seen_urls:
                continue
            seen_urls.add(abs_url)
            title = tag.get_text(strip=True) or abs_url
            links.append((title, abs_url))

        return links

    @staticmethod
    def _content_hash(data: bytes) -> str:
        """Return a SHA-256 hex digest for content diffing."""
        return hashlib.sha256(data).hexdigest()

    # ------------------------------------------------------------------
    # Policy processing
    # ------------------------------------------------------------------

    async def _process_policy(
        self,
        client: httpx.AsyncClient,
        institution: dict[str, str],
        title: str,
        url: str,
    ) -> RawItem | None:
        """Download a policy document and return a RawItem if new/changed."""
        if not self._is_url_allowed(url):
            logger.warning(
                "university_policy_url_rejected",
                source_id=self.config.id,
                url=url,
                institution=institution.get("name", "<unknown>"),
                reason="domain not in allowlist",
            )
            return None

        resp = await self._fetch_with_retries(client, url)
        if resp is None:
            return None

        content_bytes = resp.content
        content_type = resp.headers.get("content-type", "")
        new_hash = self._content_hash(content_bytes)

        hash_key = url
        old_hash = self._known_hashes.get(hash_key)

        if old_hash == new_hash:
            logger.debug(
                "university_policy_unchanged",
                source_id=self.config.id,
                url=url,
            )
            return None

        self._known_hashes[hash_key] = new_hash

        # Determine document type
        is_pdf = "application/pdf" in content_type or url.lower().endswith(".pdf")
        doc_type = "pdf" if is_pdf else "html"

        # Archive to MinIO
        minio_uri: str | None = None
        if self._archive_pdfs or not is_pdf:
            minio_uri = self._archive_document(
                content_bytes, url, new_hash, doc_type, content_type
            )

        # Build summary from HTML content when possible
        summary = ""
        if not is_pdf:
            soup = BeautifulSoup(content_bytes, "html.parser")
            text = soup.get_text(separator=" ", strip=True)
            summary = text[:500] if len(text) > 500 else text

        change_type = "new" if old_hash is None else "changed"

        raw_data: dict[str, Any] = {
            "title": title,
            "url": url,
            "institution": institution["name"],
            "document_type": doc_type,
            "content_hash": new_hash,
            "change_type": change_type,
            "content_length": len(content_bytes),
        }
        if minio_uri:
            raw_data["minio_uri"] = minio_uri
            raw_data["retention_class"] = "evidentiary"

        return RawItem(
            title=f"[{institution['name']}] {title}",
            url=url,
            summary=summary,
            raw_data=raw_data,
            occurred_at=datetime.now(UTC),
        )

    # ------------------------------------------------------------------
    # MinIO archival
    # ------------------------------------------------------------------

    @staticmethod
    def _archive_document(
        content: bytes,
        source_url: str,
        content_hash: str,
        doc_type: str,
        content_type: str,
    ) -> str | None:
        """Upload a policy document to MinIO and return the URI."""
        try:
            client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
            )

            if not client.bucket_exists(_ARTIFACT_BUCKET):
                with contextlib.suppress(S3Error):
                    client.make_bucket(_ARTIFACT_BUCKET)

            ext = "pdf" if doc_type == "pdf" else "html"
            object_name = f"policies/{content_hash[:16]}.{ext}"

            mime = content_type.split(";")[0].strip() if content_type else (
                "application/pdf" if doc_type == "pdf" else "text/html"
            )

            data = io.BytesIO(content)
            client.put_object(
                _ARTIFACT_BUCKET,
                object_name,
                data,
                length=len(content),
                content_type=mime,
            )

            uri = f"minio://{_ARTIFACT_BUCKET}/{object_name}"
            logger.info(
                "university_policy_archived",
                uri=uri,
                source_url=source_url,
                size=len(content),
            )
            return uri

        except Exception:
            logger.exception(
                "university_policy_archive_failed",
                source_url=source_url,
            )
            return None

    # ------------------------------------------------------------------
    # Dedupe
    # ------------------------------------------------------------------

    def dedupe_key(self, item: RawItem) -> str:
        url = item.url or ""
        content_hash = item.raw_data.get("content_hash", "")
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]
        return f"university_policy:{self.config.id}:{url_hash}:{content_hash[:8]}"
