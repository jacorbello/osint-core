"""Tests for alert escalation logic and digest compilation."""

from osint_core.services.alerting import should_escalate


def test_escalate_on_severity_increase():
    assert (
        should_escalate(
            current_severity="high",
            previous_severity="medium",
            corroborating_sources=1,
        )
        is True
    )


def test_escalate_on_corroboration():
    assert (
        should_escalate(
            current_severity="medium",
            previous_severity="medium",
            corroborating_sources=3,
        )
        is True
    )


def test_no_escalate_same_severity_few_sources():
    assert (
        should_escalate(
            current_severity="medium",
            previous_severity="medium",
            corroborating_sources=1,
        )
        is False
    )


def test_escalate_info_to_low():
    """Even a single step up in severity should trigger escalation."""
    assert (
        should_escalate(
            current_severity="low",
            previous_severity="info",
            corroborating_sources=0,
        )
        is True
    )


def test_no_escalate_severity_decrease():
    """A severity decrease should not trigger escalation."""
    assert (
        should_escalate(
            current_severity="medium",
            previous_severity="high",
            corroborating_sources=1,
        )
        is False
    )


def test_escalate_many_sources_even_low_severity():
    """3+ corroborating sources should escalate regardless of severity level."""
    assert (
        should_escalate(
            current_severity="low",
            previous_severity="low",
            corroborating_sources=5,
        )
        is True
    )


def test_no_escalate_two_sources_same_severity():
    """Two sources with same severity is not enough for escalation."""
    assert (
        should_escalate(
            current_severity="high",
            previous_severity="high",
            corroborating_sources=2,
        )
        is False
    )


def test_escalate_critical_from_high():
    """Escalation from high to critical should trigger."""
    assert (
        should_escalate(
            current_severity="critical",
            previous_severity="high",
            corroborating_sources=1,
        )
        is True
    )


def test_escalate_exactly_three_sources():
    """Exactly three corroborating sources should trigger escalation."""
    assert (
        should_escalate(
            current_severity="info",
            previous_severity="info",
            corroborating_sources=3,
        )
        is True
    )
