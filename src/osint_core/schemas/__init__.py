"""Pydantic v2 request/response schemas for all API resources."""

from osint_core.schemas.alert import (
    AlertList,
    AlertResponse,
    AlertUpdateRequest,
)
from osint_core.schemas.audit import AuditLogList, AuditLogResponse
from osint_core.schemas.brief import BriefCreateRequest, BriefList, BriefResponse
from osint_core.schemas.common import (
    CollectionResponse,
    JobStatusEnum,
    PageInfo,
    ProblemDetails,
    RetentionClassEnum,
    SeverityEnum,
    StatusEnum,
)
from osint_core.schemas.entity import EntityList, EntityResponse
from osint_core.schemas.event import EventList, EventResponse
from osint_core.schemas.indicator import IndicatorList, IndicatorResponse
from osint_core.schemas.job import JobCreateRequest, JobKindEnum, JobList, JobResponse
from osint_core.schemas.plan import (
    PlanActivationRequest,
    PlanCreateRequest,
    PlanValidationResult,
    PlanVersionList,
    PlanVersionResponse,
)

__all__ = [
    "AlertList",
    "AlertResponse",
    "AlertUpdateRequest",
    "AuditLogList",
    "AuditLogResponse",
    "BriefCreateRequest",
    "BriefList",
    "BriefResponse",
    "CollectionResponse",
    "EntityList",
    "EntityResponse",
    "EventList",
    "EventResponse",
    "IndicatorList",
    "IndicatorResponse",
    "JobCreateRequest",
    "JobKindEnum",
    "JobList",
    "JobResponse",
    "JobStatusEnum",
    "PageInfo",
    "PlanActivationRequest",
    "PlanCreateRequest",
    "PlanValidationResult",
    "PlanVersionList",
    "PlanVersionResponse",
    "ProblemDetails",
    "RetentionClassEnum",
    "SeverityEnum",
    "StatusEnum",
]
