"""OSINT data models — import all models so Base.metadata is fully populated."""

from osint_core.models.alert import Alert
from osint_core.models.artifact import Artifact
from osint_core.models.audit import AuditLog
from osint_core.models.base import Base
from osint_core.models.brief import Brief
from osint_core.models.entity import Entity
from osint_core.models.event import Event, event_artifacts, event_entities, event_indicators
from osint_core.models.indicator import Indicator
from osint_core.models.job import Job
from osint_core.models.plan import PlanVersion
from osint_core.models.user_preference import UserPreference
from osint_core.models.watch import Watch, watch_events

__all__ = [
    "Alert",
    "Artifact",
    "AuditLog",
    "Base",
    "Brief",
    "Entity",
    "Event",
    "Indicator",
    "Job",
    "PlanVersion",
    "UserPreference",
    "Watch",
    "event_artifacts",
    "event_entities",
    "event_indicators",
    "watch_events",
]
