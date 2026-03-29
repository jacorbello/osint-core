from pathlib import Path

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


def test_validate_cyber_threat_intel_yaml():
    """cyber-threat-intel.yaml must pass validation."""
    engine = PlanEngine()
    plan_path = Path(__file__).resolve().parents[1] / "plans" / "cyber-threat-intel.yaml"
    yaml_str = plan_path.read_text()
    result = engine.validate_yaml(yaml_str)
    assert result.is_valid, f"Errors: {result.errors}"
    assert result.parsed["version"] == 2
    assert result.parsed["plan_type"] == "child"


def test_validate_austin_terror_watch_yaml():
    """austin-terror-watch.yaml must pass validation with updated recency."""
    engine = PlanEngine()
    plan_path = Path(__file__).resolve().parents[1] / "plans" / "austin-terror-watch.yaml"
    yaml_str = plan_path.read_text()
    result = engine.validate_yaml(yaml_str)
    assert result.is_valid, f"Errors: {result.errors}"
    assert result.parsed["scoring"]["recency_half_life_hours"] == 168


def test_validate_brand_reputation_template_yaml():
    """brand-reputation.yaml template must pass v2 validation (includes reddit source)."""
    engine = PlanEngine()
    plan_path = (
        Path(__file__).resolve().parents[1] / "plans" / "templates" / "brand-reputation.yaml"
    )
    yaml_str = plan_path.read_text()
    result = engine.validate_yaml(yaml_str)
    assert result.is_valid, f"Errors: {result.errors}"
    assert result.parsed["version"] == 2
    source_types = [s["type"] for s in result.parsed["sources"]]
    assert "reddit" in source_types, "reddit source type must be present and valid"


def test_validate_v2_reddit_source_type():
    """v2 schema must accept 'reddit' as a valid source type."""
    engine = PlanEngine()
    yaml_str = """
version: 2
plan_id: reddit-test-v2
plan_type: child
retention_class: standard
sources:
  - id: reddit_brand
    type: reddit
    schedule_cron: "*/30 * * * *"
scoring:
  recency_half_life_hours: 24
  source_reputation:
    reddit_brand: 0.45
  ioc_match_boost: 1.0
notifications:
  routes:
    - name: alerts
      channels:
        - type: gotify
"""
    result = engine.validate_yaml(yaml_str)
    assert result.is_valid, f"Errors: {result.errors}"
    assert result.parsed["sources"][0]["type"] == "reddit"


def test_validate_v1_reddit_source_type():
    """v1 schema must accept 'reddit' as a valid source type."""
    engine = PlanEngine()
    yaml_str = """
version: 1
plan_id: reddit-test-v1
sources:
  - id: reddit_brand
    type: reddit
    schedule_cron: "*/30 * * * *"
scoring:
  recency_half_life_hours: 24
  source_reputation:
    reddit_brand: 0.45
  ioc_match_boost: 1.0
notifications:
  routes:
    - name: alerts
      channels:
        - type: gotify
"""
    result = engine.validate_yaml(yaml_str)
    assert result.is_valid, f"Errors: {result.errors}"
    assert result.parsed["sources"][0]["type"] == "reddit"


def test_validate_cal_prospecting_yaml():
    """cal-prospecting.yaml must pass validation."""
    engine = PlanEngine()
    plan_path = Path(__file__).resolve().parents[1] / "plans" / "cal-prospecting.yaml"
    yaml_str = plan_path.read_text()
    result = engine.validate_yaml(yaml_str)
    assert result.is_valid, f"Errors: {result.errors}"
    assert result.parsed["version"] == 2
    assert result.parsed["plan_type"] == "child"
    source_types = [s["type"] for s in result.parsed["sources"]]
    assert "university_policy" in source_types
    assert "xai_x_search" in source_types
    assert "rss" in source_types


def test_validate_v2_university_policy_source_type():
    """v2 schema must accept 'university_policy' as a valid source type."""
    engine = PlanEngine()
    yaml_str = """
version: 2
plan_id: univ-test-v2
plan_type: child
retention_class: standard
sources:
  - id: univ_uc
    type: university_policy
    schedule_cron: "0 8 * * 1"
scoring:
  recency_half_life_hours: 168
  source_reputation:
    univ_uc: 0.95
  ioc_match_boost: 1.5
notifications:
  routes:
    - name: alerts
      channels:
        - type: gotify
"""
    result = engine.validate_yaml(yaml_str)
    assert result.is_valid, f"Errors: {result.errors}"
    assert result.parsed["sources"][0]["type"] == "university_policy"


def test_validate_v1_xai_x_search_source_type():
    """v1 schema must accept 'xai_x_search' as a valid source type."""
    engine = PlanEngine()
    yaml_str = """
version: 1
plan_id: xai-test-v1
sources:
  - id: xai_search
    type: xai_x_search
    schedule_cron: "0 */6 * * *"
scoring:
  recency_half_life_hours: 24
  source_reputation:
    xai_search: 0.7
  ioc_match_boost: 1.0
notifications:
  routes:
    - name: alerts
      channels:
        - type: gotify
"""
    result = engine.validate_yaml(yaml_str)
    assert result.is_valid, f"Errors: {result.errors}"
    assert result.parsed["sources"][0]["type"] == "xai_x_search"


def test_validate_v1_university_policy_source_type():
    """v1 schema must accept 'university_policy' as a valid source type."""
    engine = PlanEngine()
    yaml_str = """
version: 1
plan_id: univ-test-v1
sources:
  - id: univ_policy
    type: university_policy
    schedule_cron: "0 8 * * 1"
scoring:
  recency_half_life_hours: 168
  source_reputation:
    univ_policy: 0.95
  ioc_match_boost: 1.5
notifications:
  routes:
    - name: alerts
      channels:
        - type: gotify
"""
    result = engine.validate_yaml(yaml_str)
    assert result.is_valid, f"Errors: {result.errors}"
    assert result.parsed["sources"][0]["type"] == "university_policy"
