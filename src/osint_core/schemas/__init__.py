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
from osint_core.schemas.lead import (
    LeadListResponse,
    LeadResponse,
    LeadStatusEnum,
    LeadTypeEnum,
    LeadUpdateRequest,
)
from osint_core.schemas.plan import (
    PlanActivationRequest,
    PlanCreateRequest,
    PlanValidationResult,
    PlanVersionList,
    PlanVersionResponse,
)
from osint_core.schemas.ui import (
    AlertBulkUpdateRequest,
    BulkUpdateChange,
    BulkUpdateIssue,
    BulkUpdateResponse,
    BulkUpdateSummary,
    DashboardSummaryResponse,
    EventRelatedMeta,
    EventRelatedResponse,
    ExportFormatEnum,
    FacetBucket,
    FacetsResponse,
    LeadBulkUpdateRequest,
    MeResponse,
    StreamEventPayload,
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
    "LeadListResponse",
    "LeadResponse",
    "LeadStatusEnum",
    "LeadTypeEnum",
    "LeadUpdateRequest",
    "PageInfo",
    "PlanActivationRequest",
    "PlanCreateRequest",
    "PlanValidationResult",
    "PlanVersionList",
    "PlanVersionResponse",
    "ProblemDetails",
    "DashboardSummaryResponse",
    "AlertBulkUpdateRequest",
    "BulkUpdateChange",
    "BulkUpdateIssue",
    "BulkUpdateResponse",
    "BulkUpdateSummary",
    "EventRelatedMeta",
    "EventRelatedResponse",
    "ExportFormatEnum",
    "FacetBucket",
    "FacetsResponse",
    "LeadBulkUpdateRequest",
    "MeResponse",
    "StreamEventPayload",
    "RetentionClassEnum",
    "SeverityEnum",
    "StatusEnum",
]
