from osint_core.services.plan_engine import PlanEngine

VALID_PLAN_YAML = """
version: 1
plan_id: test-plan
description: "Test plan"
retention_class: standard

sources:
  - id: cisa_kev
    type: cisa_kev
    url: "https://www.cisa.gov/known-exploited-vulnerabilities-catalog"
    weight: 1.2

scoring:
  recency_half_life_hours: 48
  source_reputation:
    cisa_kev: 1.3
  ioc_match_boost: 2.5
  force_alert:
    min_severity: high
    tags_any: ["force_alert"]

notifications:
  default_dedupe_window_minutes: 90
  quiet_hours:
    timezone: "America/Chicago"
    start: "22:00"
    end: "07:00"
  routes:
    - name: critical_gotify
      when:
        severity_gte: high
      channels:
        - type: gotify
          application: "osint-alerts"
          priority: 8
"""


def test_validate_valid_plan():
    engine = PlanEngine()
    result = engine.validate_yaml(VALID_PLAN_YAML)
    assert result.is_valid is True
    assert len(result.errors) == 0


def test_validate_missing_required_field():
    bad_yaml = "version: 1\nplan_id: test\n"
    engine = PlanEngine()
    result = engine.validate_yaml(bad_yaml)
    assert result.is_valid is False
    assert any("sources" in e or "required" in e.lower() for e in result.errors)


def test_validate_rejects_embedded_secrets():
    plan_with_secret = VALID_PLAN_YAML + '\n  api_key: "sk-12345abcdef"'
    engine = PlanEngine()
    result = engine.validate_yaml(plan_with_secret)
    assert result.is_valid is False
    assert any("secret" in e.lower() for e in result.errors)


def test_compute_content_hash_is_deterministic():
    engine = PlanEngine()
    h1 = engine.content_hash(VALID_PLAN_YAML)
    h2 = engine.content_hash(VALID_PLAN_YAML)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex
