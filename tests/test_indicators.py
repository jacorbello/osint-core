"""Tests for indicator extraction and normalization service."""

from osint_core.services.indicators import extract_indicators, normalize_indicator


def test_extract_cve():
    text = "Critical vulnerability CVE-2026-12345 affects Apache"
    indicators = extract_indicators(text)
    assert any(i["type"] == "cve" and i["value"] == "CVE-2026-12345" for i in indicators)


def test_extract_domain():
    text = "Malware phones home to evil.example.com for C2"
    indicators = extract_indicators(text)
    assert any(i["type"] == "domain" and i["value"] == "evil.example.com" for i in indicators)


def test_extract_ip():
    text = "C2 server at 192.168.1.100"
    indicators = extract_indicators(text)
    assert any(i["type"] == "ip" and i["value"] == "192.168.1.100" for i in indicators)


def test_extract_url():
    text = "Download from https://evil.com/payload.exe"
    indicators = extract_indicators(text)
    assert any(i["type"] == "url" for i in indicators)


def test_extract_hash():
    text = "SHA-256: e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    indicators = extract_indicators(text)
    assert any(i["type"] == "hash" and "e3b0c44" in i["value"] for i in indicators)


def test_normalize_domain():
    assert normalize_indicator("domain", "EVIL.Example.COM") == "evil.example.com"


def test_normalize_url():
    result = normalize_indicator("url", "HTTP://Evil.COM/path?b=2&a=1")
    assert result.startswith("http://evil.com/")


def test_extract_multiple_indicators():
    """Extract multiple indicator types from a single text."""
    text = (
        "CVE-2024-1234 was exploited via 10.0.0.1 "
        "downloading from https://bad.example.com/malware.bin "
        "with hash d7a8fbb307d7809469ca9abcb0082e4f8d5651e46d3cdb762d02d0bf37c9e592"
    )
    indicators = extract_indicators(text)
    types = {i["type"] for i in indicators}
    assert "cve" in types
    assert "ip" in types
    assert "url" in types
    assert "hash" in types


def test_extract_md5_hash():
    text = "MD5: d41d8cd98f00b204e9800998ecf8427e"
    indicators = extract_indicators(text)
    assert any(i["type"] == "hash" and "d41d8cd9" in i["value"] for i in indicators)


def test_extract_no_indicators():
    text = "This is a normal sentence with no indicators."
    indicators = extract_indicators(text)
    assert indicators == []


def test_normalize_ip_is_noop():
    """IP normalization should return the IP as-is."""
    assert normalize_indicator("ip", "192.168.1.1") == "192.168.1.1"


def test_normalize_cve_uppercase():
    """CVE normalization should uppercase."""
    assert normalize_indicator("cve", "cve-2024-1234") == "CVE-2024-1234"


def test_normalize_hash_lowercase():
    """Hash normalization should lowercase."""
    assert normalize_indicator("hash", "D41D8CD98F00B204") == "d41d8cd98f00b204"


def test_normalize_url_sorts_query_params():
    """URL normalization should sort query parameters."""
    result = normalize_indicator("url", "https://example.com/path?z=3&a=1&m=2")
    assert "a=1" in result
    assert result.index("a=1") < result.index("m=2") < result.index("z=3")


def test_extract_deduplicates():
    """Same indicator appearing twice should only be extracted once."""
    text = "See CVE-2024-1234 and again CVE-2024-1234"
    indicators = extract_indicators(text)
    cves = [i for i in indicators if i["type"] == "cve"]
    assert len(cves) == 1


class TestDomainFalsePositives:
    """Regression tests: sentence fragments must not be extracted as domains."""

    def test_word_dot_word_not_domain(self):
        text = "The robbery occurred last month.The suspect fled on foot."
        indicators = extract_indicators(text)
        domains = [i for i in indicators if i["type"] == "domain"]
        assert domains == []

    def test_multiple_false_positives_rejected(self):
        for fragment in [
            "night.Deputies responded to the scene",
            "damages.The fire was caused by",
            "Safety.Troopers arrived at the scene",
            "families.Principal Smith addressed",
        ]:
            indicators = extract_indicators(fragment)
            domains = [i for i in indicators if i["type"] == "domain"]
            assert domains == [], f"False positive domain in: {fragment!r}"

    def test_valid_domain_still_extracted(self):
        text = "Malware phones home to evil.example.com for C2"
        indicators = extract_indicators(text)
        domains = [i for i in indicators if i["type"] == "domain"]
        assert any(i["value"] == "evil.example.com" for i in domains)

    def test_multi_level_tld_extracted(self):
        text = "C2 at sub.domain.co.uk and also malware.gov.ru"
        indicators = extract_indicators(text)
        domains = [i for i in indicators if i["type"] == "domain"]
        values = {d["value"] for d in domains}
        assert "sub.domain.co.uk" in values
        assert "malware.gov.ru" in values
