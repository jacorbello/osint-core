"""Lead matching service — deduplicates events into leads with confidence scoring."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

from osint_core.models.event import Event
from osint_core.models.lead import Lead

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CONSTITUTIONAL_LABELS = frozenset({
    "1A-free-speech",
    "1A-religion",
    "1A-assembly",
    "1A-press",
    "14A-due-process",
    "14A-equal-protection",
    "parental-rights",
})

VALID_SEVERITIES = frozenset({"info", "low", "medium", "high", "critical"})

DEFAULT_CONFIDENCE_THRESHOLD = 0.3


@dataclass
class LeadMatcherConfig:
    """Configuration for lead matching, typically derived from plan YAML."""

    plan_id: str
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
    source_reputation: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------

def _normalize(value: str) -> str:
    """Lowercase and strip whitespace for consistent hashing."""
    return value.lower().strip()


def compute_incident_fingerprint(
    institution: str, key: str, plan_id: str | None = None,
) -> str:
    """Fingerprint for incident leads: institution + affected person or source URL hash.

    Includes plan_id so identical incidents in different plans do not collide.
    """
    raw = f"incident|{_normalize(institution)}|{_normalize(key)}"
    if plan_id is not None:
        raw = f"{raw}|plan:{plan_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


def compute_policy_fingerprint(
    institution: str, policy_name: str, plan_id: str | None = None,
) -> str:
    """Fingerprint for policy leads: institution + normalized policy name.

    Includes plan_id so identical policies in different plans do not collide.
    """
    raw = f"policy|{_normalize(institution)}|{_normalize(policy_name)}"
    if plan_id is not None:
        raw = f"{raw}|plan:{plan_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


def compute_fingerprint(
    lead_type: str, institution: str, key: str, plan_id: str | None = None,
) -> str:
    """Dispatch to the appropriate fingerprint strategy.

    If plan_id is provided, it is incorporated into the fingerprint to scope
    deduplication by plan.
    """
    if lead_type == "policy":
        return compute_policy_fingerprint(institution, key, plan_id=plan_id)
    return compute_incident_fingerprint(institution, key, plan_id=plan_id)


# ---------------------------------------------------------------------------
# Confidence scoring
# ---------------------------------------------------------------------------

def compute_confidence(
    source_count: int,
    source_types: set[str],
    severity: str | None,
    entity_completeness: float,
    source_reputation: dict[str, float] | None = None,
    source_ids: list[str] | None = None,
) -> float:
    """Compute lead confidence score (0.0-1.0).

    Factors:
        - source_count: number of corroborating events
        - source_types: unique source type set (e.g. {"rss", "xai_x_search"})
        - severity: event severity label
        - entity_completeness: 0.0-1.0 how complete entity extraction is
        - source_reputation: source_id -> trust score mapping
        - source_ids: list of source_ids for reputation lookup
    """
    # Base: number of sources (diminishing returns)
    source_factor = min(1.0, 0.3 + 0.15 * source_count)

    # Cross-source corroboration bonus
    cross_source_bonus = min(0.2, 0.1 * (len(source_types) - 1)) if len(source_types) > 1 else 0.0

    # Severity factor
    severity_map = {"critical": 0.25, "high": 0.2, "medium": 0.15, "low": 0.1, "info": 0.05}
    severity_factor = severity_map.get(severity or "info", 0.05)

    # Entity completeness contribution
    entity_factor = 0.15 * entity_completeness

    # Source reputation bonus (average of known sources)
    rep_bonus = 0.0
    if source_reputation and source_ids:
        known = [source_reputation[sid] for sid in source_ids if sid in source_reputation]
        if known:
            rep_bonus = 0.1 * (sum(known) / len(known))

    raw = source_factor + cross_source_bonus + severity_factor + entity_factor + rep_bonus
    return float(min(1.0, max(0.0, raw)))


# ---------------------------------------------------------------------------
# Entity completeness heuristic
# ---------------------------------------------------------------------------

def _entity_completeness(event: Event) -> float:
    """Estimate entity extraction completeness from event metadata."""
    score = 0.0
    metadata = event.metadata_ or {}

    # Check for institution
    if metadata.get("institution"):
        score += 0.3
    # Check for jurisdiction
    if metadata.get("jurisdiction"):
        score += 0.2
    # Check for constitutional basis (only count valid labels)
    basis = metadata.get("constitutional_basis", [])
    valid_basis = [b for b in basis if b in CONSTITUTIONAL_LABELS]
    if valid_basis:
        score += 0.3
    # Check for lead_type classification
    if metadata.get("lead_type"):
        score += 0.2

    return min(1.0, score)


# ---------------------------------------------------------------------------
# LeadMatcher
# ---------------------------------------------------------------------------

class LeadMatcher:
    """Matches enriched events to leads, creating or updating as needed."""

    def __init__(self, config: LeadMatcherConfig) -> None:
        self.config = config

    async def match_event_to_lead(self, event: Event, db: AsyncSession) -> Lead | None:
        """Create or update a Lead from an enriched event.

        Returns the Lead if above confidence threshold, else None.
        """
        metadata = event.metadata_ or {}

        # Extract and normalize lead_type
        raw_lead_type = metadata.get("lead_type")
        lead_type = raw_lead_type.strip().lower() if isinstance(raw_lead_type, str) else "incident"
        if lead_type not in {"incident", "policy"}:
            lead_type = "incident"
        institution = metadata.get("institution", "")
        jurisdiction = metadata.get("jurisdiction")
        constitutional_basis = [
            b for b in metadata.get("constitutional_basis", [])
            if b in CONSTITUTIONAL_LABELS
        ]

        # Determine fingerprint key
        if lead_type == "policy":
            key = metadata.get("policy_name") or event.title or event.source_id
        else:
            key = metadata.get("affected_person") or event.title or event.source_id

        if not institution:
            # Fall back to source_id-based institution grouping
            institution = event.source_id

        fingerprint = compute_fingerprint(
            lead_type, institution, key, plan_id=self.config.plan_id,
        )

        # Look up existing lead
        result = await db.execute(
            select(Lead).where(Lead.dedupe_fingerprint == fingerprint)
        )
        existing = result.scalar_one_or_none()

        if existing is not None:
            return await self._update_lead(existing, event, db)

        return await self._create_lead(
            fingerprint=fingerprint,
            lead_type=lead_type,
            institution=institution,
            jurisdiction=jurisdiction,
            constitutional_basis=constitutional_basis,
            event=event,
            db=db,
        )

    async def _create_lead(
        self,
        *,
        fingerprint: str,
        lead_type: str,
        institution: str,
        jurisdiction: str | None,
        constitutional_basis: list[str],
        event: Event,
        db: AsyncSession,
    ) -> Lead | None:
        """Create a new Lead from event data."""
        completeness = _entity_completeness(event)
        source_type = _source_type(event.source_id)
        severity = _normalize_severity(event.severity)

        confidence = compute_confidence(
            source_count=1,
            source_types={source_type},
            severity=severity,
            entity_completeness=completeness,
            source_reputation=self.config.source_reputation,
            source_ids=[event.source_id],
        )

        if confidence < self.config.confidence_threshold:
            return None

        now = datetime.now(UTC)
        lead = Lead(
            lead_type=lead_type,
            status="new",
            title=event.title or f"Lead from {event.source_id}",
            summary=event.nlp_summary or event.summary,
            constitutional_basis=constitutional_basis,
            jurisdiction=jurisdiction,
            institution=institution,
            severity=severity,
            confidence=confidence,
            dedupe_fingerprint=fingerprint,
            plan_id=self.config.plan_id,
            event_ids=[event.id],
            entity_ids=[],
            first_surfaced_at=now,
            last_updated_at=now,
        )
        db.add(lead)
        return lead

    async def _update_lead(
        self,
        lead: Lead,
        event: Event,
        db: AsyncSession,
    ) -> Lead:
        """Attach event to existing lead and recompute confidence."""
        # Append event ID if not already present
        if event.id not in lead.event_ids:
            set_committed_value(lead, "event_ids", [*lead.event_ids, event.id])

        # Update severity first so confidence uses the best value
        event_severity = _normalize_severity(event.severity)
        if event_severity and _severity_rank(event_severity) > _severity_rank(lead.severity):
            lead.severity = event_severity

        # Recompute confidence with updated source info
        source_ids = await _collect_source_ids(lead, event, db)
        source_types = {_source_type(sid) for sid in source_ids}
        completeness = _entity_completeness(event)

        lead.confidence = compute_confidence(
            source_count=len(lead.event_ids),
            source_types=source_types,
            severity=lead.severity,
            entity_completeness=completeness,
            source_reputation=self.config.source_reputation,
            source_ids=source_ids,
        )

        # Merge constitutional basis
        existing_basis = set(lead.constitutional_basis or [])
        event_basis = set(
            b for b in (event.metadata_ or {}).get("constitutional_basis", [])
            if b in CONSTITUTIONAL_LABELS
        )
        merged = sorted(existing_basis | event_basis)
        if merged != sorted(existing_basis):
            set_committed_value(lead, "constitutional_basis", merged)

        lead.last_updated_at = datetime.now(UTC)
        return lead


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SEVERITY_RANKS = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def _severity_rank(severity: str | None) -> int:
    return _SEVERITY_RANKS.get(severity or "info", 0)


def _normalize_severity(severity: str | None) -> str | None:
    """Return severity if valid, otherwise None."""
    if severity is None:
        return None
    normed = severity.strip().lower()
    return normed if normed in VALID_SEVERITIES else None


def _source_type(source_id: str) -> str:
    """Infer source type from source_id prefix convention."""
    if source_id.startswith("x_"):
        return "xai_x_search"
    if source_id.startswith("rss_"):
        return "rss"
    if source_id.startswith("univ_"):
        return "university_policy"
    return "unknown"


async def _collect_source_ids(
    lead: Lead, new_event: Event, db: AsyncSession,
) -> list[str]:
    """Collect unique source IDs from all events attached to the lead."""
    existing_ids = [eid for eid in lead.event_ids if eid != new_event.id]
    source_ids: set[str] = {new_event.source_id}
    if existing_ids:
        result = await db.execute(
            select(Event.source_id).where(Event.id.in_(existing_ids))
        )
        source_ids.update(row[0] for row in result.all())
    return sorted(source_ids)
