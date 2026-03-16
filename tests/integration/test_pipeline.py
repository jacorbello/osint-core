"""End-to-end pipeline integration tests.

Exercises the full data flow through mocked external services:
Plan validation -> Source ingest -> Event creation -> Indicator extraction ->
Scoring -> Alert evaluation -> Notification dispatch -> Brief generation.

No real Postgres, Redis, or Qdrant needed.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from osint_core.connectors.base import SourceConfig
from osint_core.connectors.cisa_kev import CisaKevConnector
from osint_core.services.alerting import compute_fingerprint, should_alert
from osint_core.services.brief_generator import BriefGenerator
from osint_core.services.indicators import extract_indicators
from osint_core.services.notification import NotificationRoute, NotificationService
from osint_core.services.plan_engine import PlanEngine
from osint_core.services.scoring import ScoringConfig, score_event, score_to_severity

# ---------------------------------------------------------------------------
# Full end-to-end pipeline test
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_full_pipeline(
    valid_plan_yaml: str,
    valid_plan_dict: dict,
    sample_kev_response: dict,
    respx_mock,
):
    """
    End-to-end pipeline test exercising:
    Plan validation -> Source ingest -> Event creation -> Indicator extraction ->
    Scoring -> Alert evaluation -> Notification dispatch -> Brief generation.

    Uses mocked external services (no real DB/Redis/Qdrant).
    """
    # ---- Step a: Plan validation ----
    engine = PlanEngine()
    result = engine.validate_yaml(valid_plan_yaml)
    assert result.is_valid is True, f"Plan validation failed: {result.errors}"
    assert result.parsed is not None
    plan = result.parsed

    # ---- Step b: Build Beat schedule ----
    schedule = engine.build_beat_schedule(plan)
    # Only the cisa_kev source has schedule_cron, so exactly 1 entry
    assert len(schedule) == 1
    assert "ingest-integration-test-plan-cisa_kev" in schedule
    entry = schedule["ingest-integration-test-plan-cisa_kev"]
    assert entry["task"] == "osint.ingest_source"
    assert entry["args"] == ["cisa_kev", "integration-test-plan"]
    assert entry["options"]["queue"] == "ingest"

    # ---- Step c: Connector fetch via mocked HTTP ----
    source_cfg = SourceConfig(
        id="cisa_kev",
        type="cisa_kev",
        url="https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json",
        weight=1.5,
    )
    connector = CisaKevConnector(source_cfg)
    respx_mock.get(source_cfg.url).mock(
        return_value=httpx.Response(200, json=sample_kev_response)
    )
    raw_items = await connector.fetch()
    assert len(raw_items) == 3
    assert raw_items[0].raw_data["cveID"] == "CVE-2024-21887"

    # ---- Step d: Indicator extraction ----
    # Combine titles + summaries from all items to extract indicators
    combined_text = " ".join(
        f"{item.title} {item.summary}" for item in raw_items
    )
    indicators = extract_indicators(combined_text)
    indicator_types = {ind["type"] for ind in indicators}

    # Should find CVEs embedded in the descriptions
    assert "cve" in indicator_types, f"Expected CVEs in indicators, got: {indicators}"
    cve_values = [ind["value"] for ind in indicators if ind["type"] == "cve"]
    assert "CVE-2024-21887" in cve_values
    assert "CVE-2023-46805" in cve_values
    assert "CVE-2024-0012" in cve_values

    # Should find the IP address 10.0.0.1 from the first vulnerability description
    assert "ip" in indicator_types, f"Expected IPs in indicators, got: {indicators}"
    ip_values = [ind["value"] for ind in indicators if ind["type"] == "ip"]
    assert "10.0.0.1" in ip_values

    # Should find the domain from the second vulnerability description
    assert "domain" in indicator_types, f"Expected domains in indicators, got: {indicators}"
    domain_values = [ind["value"] for ind in indicators if ind["type"] == "domain"]
    assert any("evil.example.com" in d for d in domain_values)

    # ---- Step e: Scoring ----
    scoring_cfg = ScoringConfig(
        recency_half_life_hours=plan["scoring"]["recency_half_life_hours"],
        source_reputation=plan["scoring"]["source_reputation"],
        
    )
    # Score a recent event with indicators
    score = score_event(
        source_id="cisa_kev",
        occurred_at=datetime.now(UTC),
        matched_keywords=0,
        total_keywords=0,
        config=scoring_cfg,
    )
    assert score > 0, "Score must be positive for a recent event"
    severity = score_to_severity(score)
    assert severity in ("low", "medium", "high", "critical")

    # With source_reputation and recent event, score should be high enough
    assert severity in ("medium", "high"), f"Expected 'medium' or 'high' severity, got '{severity}' (score={score})"

    # ---- Step f: Alert evaluation ----
    alert_threshold = 0.5
    alert_fires = should_alert(score=score, severity=severity, threshold=alert_threshold)
    assert alert_fires is True, "High-severity event with score > threshold should trigger alert"

    # Verify fingerprint is deterministic
    indicator_values = [ind["value"] for ind in indicators]
    fp1 = compute_fingerprint(
        plan_id=plan["plan_id"],
        indicators=indicator_values,
        canonical_url=raw_items[0].url,
    )
    fp2 = compute_fingerprint(
        plan_id=plan["plan_id"],
        indicators=indicator_values,
        canonical_url=raw_items[0].url,
    )
    assert fp1 == fp2
    assert len(fp1) == 64  # SHA-256 hex

    # ---- Step g: Notification routing ----
    routes = [
        NotificationRoute(
            name="critical_gotify",
            severity_gte="high",
            channels=[{"type": "gotify", "application": "osint-alerts", "priority": 8}],
        ),
        NotificationRoute(
            name="all_alerts",
            severity_gte="low",
            channels=[{"type": "webhook", "url": "https://hooks.example.com/osint"}],
        ),
    ]
    svc = NotificationService(routes=routes)
    matched = svc.match_routes(severity)
    assert len(matched) == 2, "Both routes should match for 'high' severity"
    matched_names = {r.name for r in matched}
    assert "critical_gotify" in matched_names
    assert "all_alerts" in matched_names

    # Format the notification message
    msg = svc.format_message(
        title=raw_items[0].title,
        summary=raw_items[0].summary,
        severity=severity,
        indicators=indicator_values[:5],
    )
    assert "title" in msg
    assert "body" in msg
    assert severity.upper() in msg["body"]

    # ---- Step h: Brief generation ----
    generator = BriefGenerator(ollama_available=False)
    events_for_brief = [
        {
            "title": item.title,
            "severity": severity,
            "score": round(score, 2),
            "source_id": "cisa_kev",
            "occurred_at": (item.occurred_at or datetime.now(UTC)).isoformat(),
        }
        for item in raw_items
    ]
    indicators_for_brief = indicators[:10]
    entities_for_brief = [
        {"name": "Ivanti", "entity_type": "vendor"},
        {"name": "PaloAlto", "entity_type": "vendor"},
    ]

    brief_md = generator.generate_from_template(
        title="Integration Test Brief",
        events=events_for_brief,
        indicators=indicators_for_brief,
        entities=entities_for_brief,
    )
    assert isinstance(brief_md, str)
    assert len(brief_md) > 100, "Brief should be a substantial markdown document"
    assert "Integration Test Brief" in brief_md
    # Template should include events, indicators, entities sections
    assert "CVE-2024-21887" in brief_md or "cisa_kev" in brief_md


# ---------------------------------------------------------------------------
# Plan-to-Beat-schedule roundtrip
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_plan_to_beat_schedule_roundtrip(valid_plan_yaml: str):
    """Validate a plan and convert to Celery Beat schedule."""
    engine = PlanEngine()

    # Validate
    result = engine.validate_yaml(valid_plan_yaml)
    assert result.is_valid is True
    plan = result.parsed

    # Content hash is deterministic
    h1 = engine.content_hash(valid_plan_yaml)
    h2 = engine.content_hash(valid_plan_yaml)
    assert h1 == h2
    assert len(h1) == 64

    # Build schedule
    schedule = engine.build_beat_schedule(plan)
    assert len(schedule) == 1  # Only cisa_kev has schedule_cron

    entry = schedule["ingest-integration-test-plan-cisa_kev"]
    assert entry["task"] == "osint.ingest_source"
    assert entry["args"] == ["cisa_kev", "integration-test-plan"]
    assert entry["options"]["queue"] == "ingest"

    # The crontab should be parsed from "0 */6 * * *"
    cron_schedule = entry["schedule"]
    # Celery crontab represents fields as sets; {0} for minute=0
    assert 0 in cron_schedule.minute
    assert len(cron_schedule.minute) == 1


# ---------------------------------------------------------------------------
# Indicator extraction pipeline
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_indicator_extraction_pipeline(sample_kev_response: dict):
    """Extract indicators from realistic feed data and verify types."""
    # Simulate raw text assembled from feed items
    text_parts = []
    for vuln in sample_kev_response["vulnerabilities"]:
        text_parts.append(f"{vuln['cveID']} - {vuln['vendorProject']} {vuln['product']}")
        text_parts.append(vuln["shortDescription"])

    combined = "\n".join(text_parts)
    indicators = extract_indicators(combined)

    # Group by type
    by_type: dict[str, list[str]] = {}
    for ind in indicators:
        by_type.setdefault(ind["type"], []).append(ind["value"])

    # Verify CVEs
    assert "cve" in by_type
    cves = by_type["cve"]
    assert "CVE-2024-21887" in cves
    assert "CVE-2023-46805" in cves
    assert "CVE-2024-0012" in cves

    # Verify IP addresses
    assert "ip" in by_type
    assert "10.0.0.1" in by_type["ip"]

    # Verify domains (malware.evil.example.com from description)
    assert "domain" in by_type
    assert any("evil.example.com" in d for d in by_type["domain"])

    # Verify URL (from PAN-OS description)
    assert "url" in by_type
    assert any("paloaltonetworks.com" in u for u in by_type["url"])

    # All indicators should have type and value keys
    for ind in indicators:
        assert "type" in ind
        assert "value" in ind
        assert ind["type"] in ("cve", "ip", "domain", "url", "hash")


# ---------------------------------------------------------------------------
# Scoring to alert pipeline
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_scoring_to_alert_pipeline():
    """Score events and verify alert logic fires correctly."""
    config = ScoringConfig(
        recency_half_life_hours=48,
        source_reputation={"cisa_kev": 1.5, "rss_threatpost": 1.0},
    )
    alert_threshold = 0.5

    # --- High-priority recent event with indicators ---
    high_score = score_event(
        source_id="cisa_kev",
        occurred_at=datetime.now(UTC),
        matched_keywords=0,
        total_keywords=0,
        config=config,
    )
    high_severity = score_to_severity(high_score)
    # 1.5 * ~1.0 * 3.0 = ~4.5 => high
    assert high_severity == "high"
    assert should_alert(high_score, high_severity, alert_threshold) is True

    # Fingerprint for dedup
    fp = compute_fingerprint(
        plan_id="integration-test-plan",
        indicators=["CVE-2024-21887", "10.0.0.1"],
        canonical_url="https://nvd.nist.gov/vuln/detail/CVE-2024-21887",
    )
    assert len(fp) == 64

    # --- Low-priority old event without indicators ---
    old_time = datetime.now(UTC) - timedelta(days=7)
    low_score = score_event(
        source_id="rss_threatpost",
        occurred_at=old_time,
        matched_keywords=0,
        total_keywords=0,
        config=config,
    )
    low_severity = score_to_severity(low_score)
    assert low_severity in ("info", "low")
    assert should_alert(low_score, low_severity, alert_threshold) is False

    # --- Critical always alerts regardless of threshold ---
    # Simulate a critical score (very high reputation + boost + recent)
    critical_config = ScoringConfig(
        recency_half_life_hours=48,
        source_reputation={"src": 5.0},
    )
    critical_score = score_event(
        source_id="src",
        occurred_at=datetime.now(UTC),
        matched_keywords=0,
        total_keywords=0,
        config=critical_config,
    )
    critical_severity = score_to_severity(critical_score)
    # With 0-1 scoring, score is clamped to 1.0 => "high" (critical is promotion-only)
    assert critical_severity in ("high", "critical")
    assert should_alert(critical_score, critical_severity, alert_threshold) is True

    # --- Notification routing based on severity ---
    routes = [
        NotificationRoute(name="critical_only", severity_gte="critical", channels=[]),
        NotificationRoute(name="high_and_above", severity_gte="high", channels=[]),
        NotificationRoute(name="all_severities", severity_gte="low", channels=[]),
    ]
    svc = NotificationService(routes=routes)

    # Critical matches all 3 routes
    critical_matches = svc.match_routes("critical")
    assert len(critical_matches) == 3

    # High matches high_and_above + all_severities
    high_matches = svc.match_routes("high")
    assert len(high_matches) == 2
    assert all(r.name != "critical_only" for r in high_matches)

    # Low matches only all_severities
    low_matches = svc.match_routes("low")
    assert len(low_matches) == 1
    assert low_matches[0].name == "all_severities"


# ---------------------------------------------------------------------------
# Brief generation with pipeline data
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_brief_generation_with_pipeline_data():
    """Generate a brief from scored events and extracted indicators."""
    generator = BriefGenerator(ollama_available=False)

    events = [
        {
            "title": "CVE-2024-21887 - Ivanti Connect Secure",
            "severity": "high",
            "score": 4.5,
            "source_id": "cisa_kev",
            "occurred_at": datetime.now(UTC).isoformat(),
        },
        {
            "title": "CVE-2024-0012 - PaloAlto PAN-OS",
            "severity": "high",
            "score": 4.5,
            "source_id": "cisa_kev",
            "occurred_at": datetime.now(UTC).isoformat(),
        },
    ]
    indicators = [
        {"value": "CVE-2024-21887", "type": "cve"},
        {"value": "CVE-2024-0012", "type": "cve"},
        {"value": "10.0.0.1", "type": "ip"},
        {"value": "malware.evil.example.com", "type": "domain"},
    ]
    entities = [
        {"name": "Ivanti", "entity_type": "vendor"},
        {"name": "PaloAlto", "entity_type": "vendor"},
    ]

    brief = generator.generate_from_template(
        title="Daily OSINT Brief",
        events=events,
        indicators=indicators,
        entities=entities,
    )

    assert isinstance(brief, str)
    assert len(brief) > 50
    assert "Daily OSINT Brief" in brief
    # The brief should reference the summary statistics
    assert "2 event(s)" in brief or "event" in brief.lower()
    assert "4 indicator(s)" in brief or "indicator" in brief.lower()


# ---------------------------------------------------------------------------
# Notification message formatting
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_notification_message_formatting():
    """Verify notification message format includes all required fields."""
    routes = [
        NotificationRoute(
            name="test_route",
            severity_gte="low",
            channels=[{"type": "gotify", "priority": 5}],
        ),
    ]
    svc = NotificationService(routes=routes)

    msg = svc.format_message(
        title="CVE-2024-21887 - Ivanti Connect Secure",
        summary="Command injection vulnerability in Ivanti Connect Secure.",
        severity="high",
        indicators=["CVE-2024-21887", "10.0.0.1", "malware.evil.example.com"],
    )

    assert msg["title"] == "CVE-2024-21887 - Ivanti Connect Secure"
    assert "HIGH" in msg["body"]
    assert "Command injection" in msg["body"]
    assert "CVE-2024-21887" in msg["body"]
    assert "10.0.0.1" in msg["body"]
    assert "malware.evil.example.com" in msg["body"]
