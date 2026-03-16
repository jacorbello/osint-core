"""Tests for alert rule evaluation."""
import pytest
from unittest.mock import MagicMock
from osint_core.services.alert_rules import evaluate_rules, parse_rules_from_plan, AlertRule


def _make_event(severity="high", source_id="cisa_kev", **kwargs):
    event = MagicMock()
    event.severity = severity
    event.source_id = source_id
    event.source_category = kwargs.get("source_category")
    event.country_code = kwargs.get("country_code")
    event.simhash = kwargs.get("simhash", 0)
    return event


class TestEvaluateRules:
    def test_severity_exact_match(self):
        rules = [AlertRule(name="critical-alert", condition={"severity": "critical"}, channels=["gotify"], cooldown_minutes=15)]
        event = _make_event(severity="critical")
        matched = evaluate_rules(event, rules)
        assert len(matched) == 1
        assert matched[0].name == "critical-alert"

    def test_severity_gte(self):
        rules = [AlertRule(name="high-plus", condition={"severity": {"gte": "high"}}, channels=["gotify"], cooldown_minutes=15)]
        event = _make_event(severity="critical")
        matched = evaluate_rules(event, rules)
        assert len(matched) == 1

    def test_no_match(self):
        rules = [AlertRule(name="critical-only", condition={"severity": "critical"}, channels=["gotify"], cooldown_minutes=15)]
        event = _make_event(severity="low")
        assert evaluate_rules(event, rules) == []

    def test_multiple_conditions_anded(self):
        rules = [AlertRule(name="kev-high", condition={"severity": {"gte": "medium"}, "source_id": "cisa_kev"}, channels=["gotify", "email"], cooldown_minutes=60)]
        event = _make_event(severity="high", source_id="cisa_kev")
        assert len(evaluate_rules(event, rules)) == 1
        event2 = _make_event(severity="high", source_id="nvd_recent")
        assert evaluate_rules(event2, rules) == []

    def test_multiple_rules_can_match(self):
        rules = [
            AlertRule(name="r1", condition={"severity": "critical"}, channels=["gotify"], cooldown_minutes=15),
            AlertRule(name="r2", condition={"severity": {"gte": "high"}}, channels=["email"], cooldown_minutes=30),
        ]
        event = _make_event(severity="critical")
        assert len(evaluate_rules(event, rules)) == 2


class TestParseRulesFromPlan:
    def test_parses_new_format(self):
        plan = {"alerts": {"rules": [
            {"name": "r1", "condition": {"severity": "high"}, "channels": ["gotify"], "cooldown_minutes": 15},
        ]}}
        rules = parse_rules_from_plan(plan)
        assert len(rules) == 1
        assert rules[0].name == "r1"

    def test_parses_legacy_notifications_format(self):
        plan = {"notifications": {"routes": [
            {"name": "legacy-high", "when": {"severity_gte": "high"}, "dedupe_window_minutes": 60},
        ]}}
        rules = parse_rules_from_plan(plan)
        assert len(rules) == 1
        assert rules[0].condition == {"severity": {"gte": "high"}}
        assert rules[0].cooldown_minutes == 60

    def test_combines_new_and_legacy(self):
        plan = {
            "alerts": {"rules": [
                {"name": "new-r", "condition": {"severity": "critical"}, "channels": ["email"], "cooldown_minutes": 10},
            ]},
            "notifications": {"routes": [
                {"name": "old-r", "when": {"severity_gte": "medium"}},
            ]},
        }
        rules = parse_rules_from_plan(plan)
        assert len(rules) == 2
