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


def test_validate_v2_master_plan():
    engine = PlanEngine()
    yaml_str = """
version: 2
plan_id: cortech-osint-master
plan_type: master
defaults:
  scoring:
    recency_half_life_hours: 12
    ioc_match_boost: 2.0
  notifications:
    default_dedupe_window_minutes: 30
    routes:
      - name: critical
        channels:
          - type: gotify
children:
  - plan_id: military-intel
watches:
  - name: home-region
    country_codes: ["USA"]
    severity_threshold: medium
"""
    result = engine.validate_yaml(yaml_str)
    assert result.is_valid, f"Errors: {result.errors}"
    assert result.parsed["plan_type"] == "master"


def test_validate_v2_child_plan():
    engine = PlanEngine()
    yaml_str = """
version: 2
plan_id: military-intel
plan_type: child
parent_plan_id: cortech-osint-master
retention_class: standard
sources:
  - id: gdelt_global
    type: gdelt_api
    url: "https://api.gdeltproject.org/api/v2/doc/doc"
    weight: 1.0
    schedule_cron: "*/15 * * * *"
scoring:
  recency_half_life_hours: 6
  source_reputation:
    gdelt_global: 0.8
  ioc_match_boost: 2.0
notifications:
  routes:
    - name: alerts
      channels:
        - type: gotify
source_profiles:
  gdelt_global:
    reliability: B
    credibility: 3
    corroboration_required: true
"""
    result = engine.validate_yaml(yaml_str)
    assert result.is_valid, f"Errors: {result.errors}"
    assert result.parsed["plan_type"] == "child"
    assert result.parsed["parent_plan_id"] == "cortech-osint-master"


def test_validate_v1_still_works():
    """v1 plans must remain backward compatible."""
    engine = PlanEngine()
    yaml_str = """
version: 1
plan_id: legacy-plan
sources:
  - id: cisa_kev
    type: cisa_kev
    url: "https://example.com/feed"
scoring:
  recency_half_life_hours: 48
  source_reputation: {}
  ioc_match_boost: 2.5
notifications:
  routes:
    - name: default
      channels:
        - type: gotify
"""
    result = engine.validate_yaml(yaml_str)
    assert result.is_valid, f"Errors: {result.errors}"


def test_build_beat_schedule_from_v2_child():
    engine = PlanEngine()
    plan = {
        "version": 2,
        "plan_id": "military-intel",
        "plan_type": "child",
        "sources": [
            {"id": "gdelt_global", "type": "gdelt_api", "schedule_cron": "*/15 * * * *"},
            {"id": "isw", "type": "rss", "schedule_cron": "0 */4 * * *"},
        ],
    }
    schedule = engine.build_beat_schedule(plan)
    assert "ingest-military-intel-gdelt_global" in schedule
    assert "ingest-military-intel-isw" in schedule


def test_validate_v2_child_with_enrichment_and_target_geo():
    """v2 child plan with enrichment and target_geo must pass validation."""
    engine = PlanEngine()
    yaml_str = """
version: 2
plan_id: austin-terror-watch
plan_type: child
sources:
  - id: gdelt_austin
    type: gdelt_api
    url: "https://api.gdeltproject.org/api/v2/doc/doc"
scoring:
  recency_half_life_hours: 168
  source_reputation:
    gdelt_austin: 0.53
  ioc_match_boost: 2.0
notifications:
  routes:
    - name: alerts
      channels:
        - type: gotify
enrichment:
  nlp_enabled: true
  mission: "Monitor terror threats in Austin"
target_geo:
  country_codes: ["USA"]
  lat: 30.2672
  lon: -97.7431
  radius_km: 100
keywords:
  - terrorism
  - attack
"""
    result = engine.validate_yaml(yaml_str)
    assert result.is_valid, f"Errors: {result.errors}"
    assert result.parsed["enrichment"]["nlp_enabled"] is True
    assert result.parsed["target_geo"]["lat"] == 30.2672
