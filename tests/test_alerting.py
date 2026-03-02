"""Tests for alert creation, fingerprint deduplication, and quiet hours."""

from datetime import time

from osint_core.services.alerting import (
    check_quiet_hours,
    compute_fingerprint,
    should_alert,
)


def test_compute_fingerprint_deterministic():
    fp1 = compute_fingerprint("plan1", ["CVE-2026-0001"], "https://example.com")
    fp2 = compute_fingerprint("plan1", ["CVE-2026-0001"], "https://example.com")
    assert fp1 == fp2


def test_compute_fingerprint_differs_for_different_inputs():
    fp1 = compute_fingerprint("plan1", ["CVE-2026-0001"], "https://example.com")
    fp2 = compute_fingerprint("plan1", ["CVE-2026-0002"], "https://example.com")
    assert fp1 != fp2


def test_should_alert_above_threshold():
    assert should_alert(score=5.0, severity="high", threshold=3.0) is True


def test_should_not_alert_below_threshold():
    assert should_alert(score=1.0, severity="low", threshold=3.0) is False


def test_compute_fingerprint_is_hex_sha256():
    """Fingerprint should be a 64-character hex string (SHA-256)."""
    fp = compute_fingerprint("plan1", ["CVE-2026-0001"], "https://example.com")
    assert len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)


def test_compute_fingerprint_sorts_indicators():
    """Indicator order should not affect the fingerprint."""
    fp1 = compute_fingerprint("plan1", ["CVE-2026-0002", "CVE-2026-0001"], "https://a.com")
    fp2 = compute_fingerprint("plan1", ["CVE-2026-0001", "CVE-2026-0002"], "https://a.com")
    assert fp1 == fp2


def test_compute_fingerprint_differs_by_plan():
    """Different plan IDs should yield different fingerprints."""
    fp1 = compute_fingerprint("plan1", ["CVE-2026-0001"], "https://example.com")
    fp2 = compute_fingerprint("plan2", ["CVE-2026-0001"], "https://example.com")
    assert fp1 != fp2


def test_compute_fingerprint_differs_by_url():
    """Different canonical URLs should yield different fingerprints."""
    fp1 = compute_fingerprint("plan1", ["CVE-2026-0001"], "https://example.com/a")
    fp2 = compute_fingerprint("plan1", ["CVE-2026-0001"], "https://example.com/b")
    assert fp1 != fp2


def test_should_alert_critical_always_alerts():
    """Critical severity should alert even with a high threshold."""
    assert should_alert(score=2.0, severity="critical", threshold=5.0) is True


def test_should_alert_at_exact_threshold():
    """Score exactly at threshold should alert."""
    assert should_alert(score=3.0, severity="medium", threshold=3.0) is True


def test_check_quiet_hours_inside_window():
    """Should return True when current time is within quiet hours."""
    current = time(2, 30)  # 2:30 AM
    quiet_start = time(22, 0)  # 10 PM
    quiet_end = time(6, 0)  # 6 AM
    assert check_quiet_hours(current, quiet_start, quiet_end) is True


def test_check_quiet_hours_outside_window():
    """Should return False when current time is outside quiet hours."""
    current = time(14, 0)  # 2 PM
    quiet_start = time(22, 0)
    quiet_end = time(6, 0)
    assert check_quiet_hours(current, quiet_start, quiet_end) is False


def test_check_quiet_hours_same_day_window():
    """Should handle quiet hours that don't span midnight."""
    current = time(13, 0)  # 1 PM
    quiet_start = time(12, 0)  # noon
    quiet_end = time(14, 0)  # 2 PM
    assert check_quiet_hours(current, quiet_start, quiet_end) is True


def test_check_quiet_hours_none_disabled():
    """When start or end is None, quiet hours are disabled (returns False)."""
    assert check_quiet_hours(time(3, 0), None, time(6, 0)) is False
    assert check_quiet_hours(time(3, 0), time(22, 0), None) is False
    assert check_quiet_hours(time(3, 0), None, None) is False
