"""Event API routes."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from osint_core.api.deps import get_current_user, get_db
from osint_core.api.errors import collection_page, problem_response, problem_response_docs
from osint_core.api.middleware.auth import UserInfo
from osint_core.models.alert import Alert
from osint_core.models.entity import Entity
from osint_core.models.event import Event, event_entities, event_indicators
from osint_core.models.indicator import Indicator
from osint_core.schemas.alert import AlertResponse
from osint_core.schemas.entity import EntityResponse
from osint_core.schemas.event import EventList, EventResponse
from osint_core.schemas.indicator import IndicatorResponse
from osint_core.schemas.ui import (
    EventRelatedMeta,
    EventRelatedResponse,
    ExportFormatEnum,
    FacetBucket,
    FacetsResponse,
)

router = APIRouter(prefix="/api/v1/events", tags=["events"])

_SORT_FIELDS = {
    "ingested_at": Event.ingested_at,
    "occurred_at": Event.occurred_at,
    "score": Event.score,
}


def _parse_sort(sort: str | None) -> Any:
    """Parse a sort parameter like '-score' or 'ingested_at' into an ORDER BY clause."""
    if sort is None:
        return Event.ingested_at.desc()

    descending = sort.startswith("-")
    field_name = sort.lstrip("-")
    column = _SORT_FIELDS.get(field_name)
    if column is None:
        # Unknown sort field — fall back to default
        return Event.ingested_at.desc()

    return column.desc().nullslast() if descending else column.asc().nullsfirst()


@router.get(
    "",
    response_model=EventList,
    operation_id="listEvents",
    responses=problem_response_docs(401, 422),
)
async def list_events(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    source_id: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    attack_technique: str | None = Query(
        default=None,
        description="Filter by MITRE ATT&CK technique ID (e.g., T1566). "
                    "Matches events whose metadata contains the given technique.",
    ),
    sort: str | None = Query(
        default=None,
        description="Sort field. Prefix with '-' for descending. "
                    "Supported: ingested_at, occurred_at, score. "
                    "Example: -score returns highest scores first.",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> EventList:
    """List events with optional filters."""
    stmt = select(Event)
    count_stmt = select(func.count()).select_from(Event)

    if source_id is not None:
        stmt = stmt.where(Event.source_id == source_id)
        count_stmt = count_stmt.where(Event.source_id == source_id)
    if severity is not None:
        stmt = stmt.where(Event.severity == severity)
        count_stmt = count_stmt.where(Event.severity == severity)
    if date_from is not None:
        stmt = stmt.where(Event.ingested_at >= date_from)
        count_stmt = count_stmt.where(Event.ingested_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Event.ingested_at <= date_to)
        count_stmt = count_stmt.where(Event.ingested_at <= date_to)
    if attack_technique is not None:
        # Use PostgreSQL JSONB containment operator (@>) to check if any
        # element in the attack_techniques array has the given technique ID.
        technique_filter = Event.metadata_.contains(
            {"attack_techniques": [{"id": attack_technique}]}
        )
        stmt = stmt.where(technique_filter)
        count_stmt = count_stmt.where(technique_filter)

    stmt = stmt.order_by(_parse_sort(sort)).limit(limit).offset(offset)

    result = await db.execute(stmt)
    items = list(result.scalars().all())

    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    return EventList(items=items, page=collection_page(offset=offset, limit=limit, total=total))


def _apply_event_filters(
    stmt,
    *,
    source_id: str | None,
    severity: str | None,
    date_from: datetime | None,
    date_to: datetime | None,
    attack_technique: str | None,
):
    if source_id is not None:
        stmt = stmt.where(Event.source_id == source_id)
    if severity is not None:
        stmt = stmt.where(Event.severity == severity)
    if date_from is not None:
        stmt = stmt.where(Event.ingested_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(Event.ingested_at <= date_to)
    if attack_technique is not None:
        stmt = stmt.where(
            Event.metadata_.contains({"attack_techniques": [{"id": attack_technique}]})
        )
    return stmt


def _serialize_event_rows(events: list[Event]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in events:
        rows.append(EventResponse.model_validate(item).model_dump(mode="json"))
    return rows


def _render_csv(rows: list[dict[str, Any]], *, fieldnames: list[str]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                key: (
                    json.dumps(value)
                    if isinstance(value, (list, dict))
                    else value
                )
                for key, value in row.items()
            }
        )
    return output.getvalue()


async def _facet_counts(
    db: AsyncSession,
    *,
    column: Any,
    filters: list[Any],
) -> list[FacetBucket]:
    """Build facet buckets for a single column."""
    stmt = (
        select(column, func.count())
        .where(*filters, column.is_not(None))
        .group_by(column)
        .order_by(func.count().desc(), column.asc())
    )
    result = await db.execute(stmt)
    return [FacetBucket(value=str(value), count=count) for value, count in result.all()]


@router.get(
    "/facets",
    response_model=FacetsResponse,
    operation_id="listEventFacets",
    responses=problem_response_docs(401, 422),
)
async def list_event_facets(
    source_id: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    attack_technique: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> FacetsResponse:
    """List filter facets for events."""
    del current_user
    filters: list[Any] = []
    applied_filters: dict[str, str] = {}

    if source_id is not None:
        filters.append(Event.source_id == source_id)
        applied_filters["source_id"] = source_id
    if severity is not None:
        filters.append(Event.severity == severity)
        applied_filters["severity"] = severity
    if date_from is not None:
        filters.append(Event.ingested_at >= date_from)
        applied_filters["date_from"] = date_from.isoformat()
    if date_to is not None:
        filters.append(Event.ingested_at <= date_to)
        applied_filters["date_to"] = date_to.isoformat()
    if attack_technique is not None:
        filters.append(
            Event.metadata_.contains({"attack_techniques": [{"id": attack_technique}]})
        )
        applied_filters["attack_technique"] = attack_technique

    facets = {
        "severity": await _facet_counts(db, column=Event.severity, filters=filters),
        "source_id": await _facet_counts(db, column=Event.source_id, filters=filters),
        "source_category": await _facet_counts(
            db, column=Event.source_category, filters=filters
        ),
        "country_code": await _facet_counts(db, column=Event.country_code, filters=filters),
    }
    return FacetsResponse(facets=facets, applied_filters=applied_filters)


@router.get(
    "/export",
    operation_id="exportEvents",
    responses=problem_response_docs(401, 422),
)
async def export_events(
    format: ExportFormatEnum = Query(default=ExportFormatEnum.csv),
    source_id: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    attack_technique: str | None = Query(default=None),
    sort: str | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=5000, description="Max rows to export"),
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> Response:
    """Export event rows as CSV or JSON."""
    del current_user
    stmt = _apply_event_filters(
        select(Event),
        source_id=source_id,
        severity=severity,
        date_from=date_from,
        date_to=date_to,
        attack_technique=attack_technique,
    )
    stmt = stmt.order_by(_parse_sort(sort)).limit(limit)

    result = await db.execute(stmt)
    rows = _serialize_event_rows(list(result.scalars().all()))

    if format == ExportFormatEnum.json:
        return JSONResponse(content=rows)

    fieldnames = list(EventResponse.model_fields.keys())
    csv_data = _render_csv(rows, fieldnames=fieldnames)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="events-export.csv"'},
    )


@router.get(
    "/{event_id}/related",
    response_model=EventRelatedResponse,
    operation_id="getEventRelated",
    responses=problem_response_docs(401, 404, 422),
)
async def get_event_related(
    event_id: UUID,
    request: Request,
    include: str | None = Query(
        default=None,
        description="Comma-delimited sections: alerts,entities,indicators",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> EventRelatedResponse:
    """Get event detail plus linked records in one response."""
    del current_user
    include_values = {"alerts", "entities", "indicators"}
    if include is None:
        requested = include_values
    else:
        requested = {value.strip() for value in include.split(",") if value.strip()}
        unknown = requested - include_values
        if unknown:
            return problem_response(
                request,
                status_code=422,
                code="validation_failed",
                detail=f"Unsupported include values: {', '.join(sorted(unknown))}",
            )  # type: ignore[return-value]

    event_result = await db.execute(select(Event).where(Event.id == event_id))
    event = event_result.scalar_one_or_none()
    if event is None:
        return problem_response(
            request,
            status_code=404,
            code="not_found",
            detail="Event not found",
        )  # type: ignore[return-value]

    alerts: list[AlertResponse] = []
    if "alerts" in requested:
        alert_result = await db.execute(select(Alert).where(Alert.event_ids.any(event_id)))
        alerts = [AlertResponse.model_validate(item) for item in alert_result.scalars().all()]

    entities: list[EntityResponse] = []
    if "entities" in requested:
        entity_result = await db.execute(
            select(Entity)
            .join(event_entities, event_entities.c.entity_id == Entity.id)
            .where(event_entities.c.event_id == event_id)
        )
        entities = [EntityResponse.model_validate(item) for item in entity_result.scalars().all()]

    indicators: list[IndicatorResponse] = []
    if "indicators" in requested:
        indicator_result = await db.execute(
            select(Indicator)
            .join(event_indicators, event_indicators.c.indicator_id == Indicator.id)
            .where(event_indicators.c.event_id == event_id)
        )
        indicators = [
            IndicatorResponse.model_validate(item)
            for item in indicator_result.scalars().all()
        ]

    return EventRelatedResponse(
        event=EventResponse.model_validate(event),
        alerts=alerts,
        entities=entities,
        indicators=indicators,
        meta=EventRelatedMeta(
            alert_count=len(alerts),
            entity_count=len(entities),
            indicator_count=len(indicators),
        ),
    )


@router.get(
    "/{event_id}",
    response_model=EventResponse,
    operation_id="getEvent",
    responses=problem_response_docs(401, 404, 422),
)
async def get_event(
    event_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> EventResponse:
    """Get a single event by ID."""
    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if event is None:
        return problem_response(
            request,
            status_code=404,
            code="not_found",
            detail="Event not found",
        )  # type: ignore[return-value]
    return event  # type: ignore[return-value]
