"""Alert rule evaluation engine."""
from __future__ import annotations

from dataclasses import dataclass

_SEVERITY_ORDER = ["info", "low", "medium", "high", "critical"]


@dataclass
class AlertRule:
    name: str
    condition: dict
    channels: list[str]
    cooldown_minutes: int


def _severity_index(s: str) -> int:
    try:
        return _SEVERITY_ORDER.index(s)
    except ValueError:
        return -1


def _match_condition_field(event, field_name: str, expected) -> bool:
    actual = getattr(event, field_name, None)
    if actual is None:
        return False

    if isinstance(expected, dict):
        if "gte" in expected:
            if field_name == "severity":
                ai, ei = _severity_index(actual), _severity_index(expected["gte"])
                if ai == -1 or ei == -1:
                    return False
                return ai >= ei
            return actual >= expected["gte"]
        if "lte" in expected:
            if field_name == "severity":
                ai, ei = _severity_index(actual), _severity_index(expected["lte"])
                if ai == -1 or ei == -1:
                    return False
                return ai <= ei
            return actual <= expected["lte"]
        return False

    return actual == expected


def evaluate_rules(event, rules: list[AlertRule]) -> list[AlertRule]:
    """Return list of rules whose conditions match the event."""
    matched = []
    for rule in rules:
        if all(
            _match_condition_field(event, field, value)
            for field, value in rule.condition.items()
        ):
            matched.append(rule)
    return matched


def parse_rules_from_plan(plan_content: dict) -> list[AlertRule]:
    """Parse alert rules from plan YAML content."""
    alerts = plan_content.get("alerts", {})
    raw_rules = alerts.get("rules", [])

    notifications = plan_content.get("notifications", {})
    legacy_routes = notifications.get("routes", [])

    rules = []
    for r in raw_rules:
        rules.append(AlertRule(
            name=r["name"],
            condition=r.get("condition", {}),
            channels=r.get("channels", ["gotify"]),
            cooldown_minutes=r.get("cooldown_minutes", 30),
        ))

    for route in legacy_routes:
        when = route.get("when", {})
        sev = when.get("severity_gte")
        if sev:
            rules.append(AlertRule(
                name=route.get("name", f"legacy-{sev}"),
                condition={"severity": {"gte": sev}},
                channels=["gotify"],
                cooldown_minutes=route.get("dedupe_window_minutes", 30),
            ))

    return rules
