"""Shared fixtures for integration tests."""

import pytest

VALID_PLAN_YAML = """\
version: 1
plan_id: integration-test-plan
description: "Integration test plan for end-to-end pipeline validation"
retention_class: standard

sources:
  - id: cisa_kev
    type: cisa_kev
    url: "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
    weight: 1.5
    schedule_cron: "0 */6 * * *"
  - id: rss_threatpost
    type: rss
    url: "https://threatpost.com/feed/"
    weight: 1.0

scoring:
  recency_half_life_hours: 48
  source_reputation:
    cisa_kev: 1.5
    rss_threatpost: 1.0
  ioc_match_boost: 3.0
  force_alert:
    min_severity: high
    tags_any:
      - force_alert

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
    - name: all_alerts
      when:
        severity_gte: low
      channels:
        - type: webhook
          url: "https://hooks.example.com/osint"
"""


SAMPLE_KEV_RESPONSE = {
    "title": "CISA Known Exploited Vulnerabilities Catalog",
    "catalogVersion": "2024.06.15",
    "dateReleased": "2024-06-15T00:00:00.000Z",
    "count": 3,
    "vulnerabilities": [
        {
            "cveID": "CVE-2024-21887",
            "vendorProject": "Ivanti",
            "product": "Connect Secure",
            "vulnerabilityName": "Ivanti Connect Secure Command Injection",
            "dateAdded": "2024-01-10",
            "shortDescription": (
                "Ivanti Connect Secure and Policy Secure contain a command "
                "injection vulnerability in the web component allowing an "
                "authenticated attacker with admin privileges to send crafted "
                "requests and execute arbitrary commands. Affected IP: 10.0.0.1"
            ),
            "requiredAction": "Apply updates per vendor instructions.",
            "dueDate": "2024-01-31",
            "knownRansomwareCampaignUse": "Known",
            "notes": "",
        },
        {
            "cveID": "CVE-2023-46805",
            "vendorProject": "Ivanti",
            "product": "Connect Secure",
            "vulnerabilityName": "Ivanti Connect Secure Auth Bypass",
            "dateAdded": "2024-01-10",
            "shortDescription": (
                "Ivanti Connect Secure and Policy Secure contain an "
                "authentication bypass vulnerability in the web component "
                "allowing an attacker to access restricted resources. "
                "C2 domain: malware.evil.example.com"
            ),
            "requiredAction": "Apply updates per vendor instructions.",
            "dueDate": "2024-01-31",
            "knownRansomwareCampaignUse": "Known",
            "notes": "",
        },
        {
            "cveID": "CVE-2024-0012",
            "vendorProject": "PaloAlto",
            "product": "PAN-OS",
            "vulnerabilityName": "PAN-OS Management Interface Auth Bypass",
            "dateAdded": "2024-06-01",
            "shortDescription": (
                "Palo Alto Networks PAN-OS management web interface contains "
                "an authentication bypass vulnerability allowing unauthenticated "
                "access. See https://security.paloaltonetworks.com/CVE-2024-0012"
            ),
            "requiredAction": "Apply updates per vendor instructions.",
            "dueDate": "2024-06-22",
            "knownRansomwareCampaignUse": "Unknown",
            "notes": "",
        },
    ],
}


@pytest.fixture()
def valid_plan_yaml() -> str:
    """Return a valid plan YAML string matching the JSON Schema."""
    return VALID_PLAN_YAML


@pytest.fixture()
def valid_plan_dict() -> dict:
    """Return the parsed plan dict from VALID_PLAN_YAML."""
    import yaml

    return yaml.safe_load(VALID_PLAN_YAML)


@pytest.fixture()
def sample_kev_response() -> dict:
    """Return a sample CISA KEV API response with realistic vulnerability data."""
    return SAMPLE_KEV_RESPONSE
