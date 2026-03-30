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
import redis.asyncio as aioredis
import redis.exceptions
import soupsieve
import structlog
from bs4 import BeautifulSoup
from minio import Minio, S3Error

from osint_core.config import settings
from osint_core.connectors.base import BaseConnector, RawItem

logger = structlog.get_logger()

_MAX_RETRIES = 3
_MAX_REDIRECTS = 10
_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
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
        # Validate and normalize allowed domain suffixes (SSRF allowlist)
        raw_suffixes = extra.get(
            "allowed_domain_suffixes", _DEFAULT_ALLOWED_DOMAIN_SUFFIXES
        )
        if isinstance(raw_suffixes, str):
            raise TypeError(
                "UniversityPolicyConnector.extra['allowed_domain_suffixes'] must be a "
                "sequence of strings (e.g. ['.edu', '.gov']), not a single string."
            )
        try:
            suffix_iterable = list(raw_suffixes)
        except TypeError as exc:
            raise TypeError(
                "UniversityPolicyConnector.extra['allowed_domain_suffixes'] must be an "
                "iterable of strings (e.g. ['.edu', '.gov'])."
            ) from exc
        normalized_suffixes: list[str] = []
        for suffix in suffix_iterable:
            if not isinstance(suffix, str):
                raise TypeError(
                    "UniversityPolicyConnector.extra['allowed_domain_suffixes'] elements "
                    "must all be strings."
                )
            normalized = suffix.strip().lower()
            if not normalized:
                raise ValueError(
                    "UniversityPolicyConnector.extra['allowed_domain_suffixes'] contains "
                    "an empty or whitespace-only string."
                )
            normalized_suffixes.append(normalized)
        self._allowed_domain_suffixes: tuple[str, ...] = tuple(normalized_suffixes)

        # Normalize allowed domains to lowercase hostnames for case-insensitive matching
        raw_allowed_domains = extra.get("allowed_domains", ())
        if isinstance(raw_allowed_domains, str):
            raw_allowed_domains = [raw_allowed_domains]
        self._allowed_domains: frozenset[str] = frozenset(
            d.strip().lower()
            for d in raw_allowed_domains
            if isinstance(d, str) and d.strip()
        )
        self._validate_selectors()
        self._validate_urls()
        self._archive_pdfs: bool = extra.get("archive_pdfs", True)
        # Redis-backed hash store keyed by source_id + URL.
        # Falls back to in-memory dict when Redis is unavailable.
        self._redis: aioredis.Redis | None = None
        self._redis_available: bool = True
        self._fallback_hashes: dict[str, str] = {}
        self._redis_hash_key = f"policy_hashes:{self.config.id}"

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

        # Reject non-global IP addresses (private, loopback, reserved, link-local, etc.)
        try:
            addr = ipaddress.ip_address(hostname)
            # For IPv6, consider IPv4-mapped addresses if present
            effective_addr = getattr(addr, "ipv4_mapped", None) or addr
            if not effective_addr.is_global:
                return False
        except ValueError:
            pass  # Not an IP address — proceed with domain checks

        # Check explicit allowed domains
        if hostname in self._allowed_domains:
            return True

        # Check allowed domain suffixes
        return any(hostname.endswith(suffix) for suffix in self._allowed_domain_suffixes)

    async def _get_redis(self) -> aioredis.Redis | None:
        """Return a shared Redis connection, or ``None`` if unavailable."""
        if not self._redis_available:
            return None
        if self._redis is not None:
            return self._redis
        try:
            self._redis = aioredis.from_url(  # type: ignore[no-untyped-call]
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
            )
            # Verify connectivity
            await self._redis.ping()
            return self._redis
        except (redis.exceptions.RedisError, OSError):
            logger.warning(
                "university_policy_redis_unavailable",
                source_id=self.config.id,
                msg="Falling back to in-memory hash store",
            )
            self._redis_available = False
            self._redis = None
            return None

    async def _mark_redis_failed(self) -> None:
        """Mark Redis as unavailable and close the client.

        After the first read or write error, the connector switches to the
        in-memory fallback for the remainder of its lifetime to avoid repeated
        failures and warning noise.
        """
        self._redis_available = False
        if self._redis is not None:
            with contextlib.suppress(Exception):
                await self._redis.aclose()
            self._redis = None

    async def _close_redis(self) -> None:
        """Close the Redis client if one was created."""
        if self._redis is not None:
            with contextlib.suppress(Exception):
                await self._redis.aclose()
            self._redis = None

    async def _get_hash(self, url: str) -> str | None:
        """Look up the stored content hash for a URL."""
        r = await self._get_redis()
        if r is not None:
            try:
                result: str | None = await r.hget(self._redis_hash_key, url)  # type: ignore[misc]
                return result
            except redis.exceptions.RedisError:
                logger.warning(
                    "university_policy_redis_read_error",
                    source_id=self.config.id,
                    url=url,
                )
                await self._mark_redis_failed()
        return self._fallback_hashes.get(url)

    async def _set_hash(self, url: str, content_hash: str) -> None:
        """Persist a content hash for a URL.

        Uses Redis when available; falls back to in-memory storage otherwise.
        """
        r = await self._get_redis()
        if r is not None:
            try:
                await r.hset(self._redis_hash_key, url, content_hash)  # type: ignore[misc]
                return
            except redis.exceptions.RedisError:
                logger.warning(
                    "university_policy_redis_write_error",
                    source_id=self.config.id,
                    url=url,
                )
                await self._mark_redis_failed()
        # Fallback path: Redis unavailable or write failed
        self._fallback_hashes[url] = content_hash

    async def fetch(self) -> list[RawItem]:
        items: list[RawItem] = []
        try:
            async with httpx.AsyncClient(
                timeout=30, follow_redirects=False
            ) as client:
                for institution in self._institutions:
                    inst_items = await self._fetch_institution(client, institution)
                    items.extend(inst_items)
        finally:
            await self._close_redis()
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

        try:
            resp = await self._fetch_with_validated_redirects(client, policy_url)
        except ValueError:
            # Redirect to disallowed host — already logged by the method
            return []
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

    async def _fetch_with_validated_redirects(
        self,
        client: httpx.AsyncClient,
        url: str,
    ) -> httpx.Response | None:
        """Fetch a URL, manually following redirects while validating each target.

        Prevents SSRF bypass where an allowed domain redirects to an internal host.
        Raises ``ValueError`` if a redirect target fails the domain allowlist check.
        """
        current_url = url
        for _ in range(_MAX_REDIRECTS):
            resp = await self._fetch_with_retries(client, current_url)
            if resp is None:
                return None

            if resp.status_code not in _REDIRECT_STATUS_CODES:
                return resp

            location = resp.headers.get("Location")
            if not location:
                return resp

            # Resolve relative redirect targets
            redirect_url = urljoin(current_url, location)

            if not self._is_url_allowed(redirect_url):
                logger.warning(
                    "university_policy_redirect_blocked",
                    source_id=self.config.id,
                    original_url=url,
                    redirect_url=redirect_url,
                    reason="redirect target not in domain allowlist",
                )
                raise ValueError(
                    f"Redirect from {current_url!r} to disallowed URL "
                    f"{redirect_url!r} blocked (SSRF mitigation)"
                )

            current_url = redirect_url

        logger.error(
            "university_policy_too_many_redirects",
            source_id=self.config.id,
            url=url,
            max_redirects=_MAX_REDIRECTS,
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

        try:
            resp = await self._fetch_with_validated_redirects(client, url)
        except ValueError:
            # Redirect to disallowed host — already logged by the method
            return None
        if resp is None:
            return None

        content_bytes = resp.content
        content_type = resp.headers.get("content-type", "")
        new_hash = self._content_hash(content_bytes)

        old_hash = await self._get_hash(url)

        if old_hash == new_hash:
            logger.debug(
                "university_policy_unchanged",
                source_id=self.config.id,
                url=url,
            )
            return None

        await self._set_hash(url, new_hash)

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
