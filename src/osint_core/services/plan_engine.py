"""Plan engine — validates OSINT collection plan YAML against JSON Schema and scans for secrets."""

import hashlib
import importlib.resources
import json
import re
from dataclasses import dataclass, field
from typing import Any

import jsonschema
import yaml
from celery.schedules import crontab


def _load_schema(version: int = 1) -> dict[str, Any]:
    """Load the plan JSON Schema from the osint_core.schemas package."""
    schema_files = importlib.resources.files("osint_core.schemas")
    filename = f"plan-v{version}.schema.json"
    schema_file = schema_files.joinpath(filename)
    result: dict[str, Any] = json.loads(schema_file.read_text(encoding="utf-8"))
    return result

SECRET_PATTERNS = [
    re.compile(r"(?:api[_-]?key|secret|password|token)\s*[:=]\s*[\"']?\S{8,}", re.I),
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),
    re.compile(r"xox[bprs]-[a-zA-Z0-9-]+"),
]


@dataclass
class ValidationResult:
    """Result of validating a plan YAML string."""

    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    parsed: dict[str, Any] | None = None


class PlanEngine:
    """Validates OSINT collection plans and computes content hashes."""

    def __init__(self) -> None:
        self._schema_v1 = _load_schema(1)
        self._schema_v2 = _load_schema(2)
        self._validator_v1 = jsonschema.Draft202012Validator(self._schema_v1)
        self._validator_v2 = jsonschema.Draft202012Validator(self._schema_v2)

    def validate_yaml(self, yaml_str: str) -> ValidationResult:
        """Validate a plan YAML string against the JSON Schema and scan for embedded secrets."""
        errors: list[str] = []

        # Parse YAML
        try:
            parsed = yaml.safe_load(yaml_str)
        except yaml.YAMLError as exc:
            return ValidationResult(is_valid=False, errors=[f"YAML parse error: {exc}"])

        if not isinstance(parsed, dict):
            return ValidationResult(is_valid=False, errors=["Plan must be a YAML mapping"])

        # Select validator based on version
        version = parsed.get("version", 1)
        validator = self._validator_v2 if version == 2 else self._validator_v1

        # JSON Schema validation
        for err in validator.iter_errors(parsed):
            errors.append(f"{err.json_path}: {err.message}")

        # Secret scan
        for pattern in SECRET_PATTERNS:
            if pattern.search(yaml_str):
                errors.append("Safety: potential secret or API key detected in plan file")
                break

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            parsed=parsed if not errors else None,
        )

    def content_hash(self, yaml_str: str) -> str:
        """Compute a deterministic SHA-256 hex digest for the plan content."""
        return hashlib.sha256(yaml_str.encode()).hexdigest()

    def build_beat_schedule(self, plan: dict[str, Any]) -> dict[str, Any]:
        """Convert a plan's sources list into a Celery Beat schedule.

        Only sources with a ``schedule_cron`` field are included.  Each entry
        dispatches the ``osint.ingest_source`` task to the ``ingest`` queue.

        Args:
            plan: Parsed plan dict (must contain a ``sources`` key).

        Returns:
            Dict suitable for ``celery_app.conf.beat_schedule``.
        """
        schedule: dict[str, Any] = {}
        for source in plan.get("sources", []):
            cron_expr = source.get("schedule_cron")
            if not cron_expr:
                continue
            source_id = source["id"]
            schedule[f"ingest-{source_id}"] = {
                "task": "osint.ingest_source",
                "schedule": _parse_cron(cron_expr),
                "args": [source_id],
                "options": {"queue": "ingest"},
            }
        return schedule


def _parse_cron(expr: str) -> crontab:
    """Parse a standard 5-field cron expression into a Celery crontab.

    Format: ``minute hour day_of_month month_of_year day_of_week``
    """
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Invalid cron expression (expected 5 fields): {expr!r}")
    return crontab(
        minute=parts[0],
        hour=parts[1],
        day_of_month=parts[2],
        month_of_year=parts[3],
        day_of_week=parts[4],
    )
