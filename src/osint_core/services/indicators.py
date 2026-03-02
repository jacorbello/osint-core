"""Indicator extraction and normalization service.

Regex-based extraction for CVEs, domains, IPs (v4), URLs, and SHA-256/MD5 hashes.
Normalization: lowercase domains/URLs, sort query params, uppercase CVEs.
"""

import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

# ---------------------------------------------------------------------------
# Regex patterns for indicator types
# ---------------------------------------------------------------------------

_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,}\b", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s\"'<>\]\)]+", re.IGNORECASE)
_IPV4_RE = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
)
_SHA256_RE = re.compile(r"\b[a-fA-F0-9]{64}\b")
_MD5_RE = re.compile(r"\b[a-fA-F0-9]{32}\b")
# Domain: word chars + hyphens + dots, ending in a 2-63 char TLD, not preceded by @ or //
_DOMAIN_RE = re.compile(
    r"(?<![/@\w])(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)"
    r"+[a-zA-Z]{2,63}\b"
)


def extract_indicators(text: str) -> list[dict]:
    """Extract IOC indicators from free text.

    Returns a list of dicts with keys ``type`` and ``value``.
    Deduplicates by (type, normalized_value).
    """
    seen: set[tuple[str, str]] = set()
    results: list[dict] = []

    def _add(ind_type: str, raw_value: str) -> None:
        normalized = normalize_indicator(ind_type, raw_value)
        key = (ind_type, normalized)
        if key not in seen:
            seen.add(key)
            results.append({"type": ind_type, "value": normalized})

    # Order matters: extract URLs before domains so we can exclude URL hostnames
    # from standalone domain matches.

    # CVEs
    for m in _CVE_RE.finditer(text):
        _add("cve", m.group())

    # URLs (must come before domains)
    url_spans: list[tuple[int, int]] = []
    for m in _URL_RE.finditer(text):
        _add("url", m.group())
        url_spans.append((m.start(), m.end()))

    # SHA-256 hashes (64 hex chars)
    for m in _SHA256_RE.finditer(text):
        _add("hash", m.group())

    # MD5 hashes (32 hex chars) — skip if it overlaps a SHA-256 match
    sha256_values = {v for t, v in seen if t == "hash" and len(v) == 64}
    for m in _MD5_RE.finditer(text):
        val = m.group().lower()
        # Skip if this 32-char string is a substring of an already-extracted SHA-256
        if any(val in sha for sha in sha256_values):
            continue
        _add("hash", m.group())

    # IPv4 addresses
    for m in _IPV4_RE.finditer(text):
        _add("ip", m.group())

    # Domains — skip any that fall inside a URL span
    for m in _DOMAIN_RE.finditer(text):
        start, end = m.start(), m.end()
        in_url = any(us <= start and end <= ue for us, ue in url_spans)
        if not in_url:
            _add("domain", m.group())

    return results


def normalize_indicator(indicator_type: str, value: str) -> str:
    """Normalize an indicator value based on its type.

    - domain: lowercase
    - url: lowercase scheme+host, sort query params
    - cve: uppercase
    - hash: lowercase
    - ip: no-op
    """
    match indicator_type:
        case "domain":
            return value.lower()
        case "url":
            return _normalize_url(value)
        case "cve":
            return value.upper()
        case "hash":
            return value.lower()
        case _:
            return value


def _normalize_url(url: str) -> str:
    """Normalize a URL: lowercase scheme + host, sort query parameters."""
    parsed = urlparse(url)
    # Lowercase scheme and netloc
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    # Sort query parameters
    if parsed.query:
        params = parse_qs(parsed.query, keep_blank_values=True)
        sorted_query = urlencode(sorted(params.items()), doseq=True)
    else:
        sorted_query = ""
    return urlunparse((scheme, netloc, parsed.path, parsed.params, sorted_query, parsed.fragment))
