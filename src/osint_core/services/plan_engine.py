"""Plan engine — validates OSINT collection plan YAML against JSON Schema and scans for secrets."""

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import jsonschema
import yaml

SCHEMA_PATH = Path(__file__).parent.parent.parent.parent / "schemas" / "plan-v1.schema.json"

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
    parsed: dict | None = None


class PlanEngine:
    """Validates OSINT collection plans and computes content hashes."""

    def __init__(self) -> None:
        self._schema: dict = {}
        if SCHEMA_PATH.exists():
            self._schema = json.loads(SCHEMA_PATH.read_text())

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

        # JSON Schema validation
        if self._schema:
            validator = jsonschema.Draft202012Validator(self._schema)
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
