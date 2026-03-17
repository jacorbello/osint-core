"""Plan management API routes."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from osint_core.api.deps import get_current_user, get_db
from osint_core.api.errors import collection_page, problem_response, problem_response_docs
from osint_core.api.middleware.auth import UserInfo
from osint_core.config import settings
from osint_core.models.plan import PlanVersion
from osint_core.schemas.plan import (
    PlanActivationRequest,
    PlanCreateRequest,
    PlanValidationResult,
    PlanVersionList,
    PlanVersionResponse,
)
from osint_core.services.plan_engine import PlanEngine
from osint_core.services.plan_store import PlanStore

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/plans", tags=["plans"])
engine = PlanEngine()
store = PlanStore()


@router.post(
    ":validate",
    response_model=PlanValidationResult,
    operation_id="validatePlan",
    responses=problem_response_docs(401, 422),
)
async def validate_plan(request: Request) -> dict[str, Any]:
    """Validate a plan YAML payload without persisting it."""
    body = await request.body()
    result = engine.validate_yaml(body.decode())
    return {
        "is_valid": result.is_valid,
        "errors": result.errors,
        "warnings": result.warnings,
    }


@router.get(
    "",
    response_model=PlanVersionList,
    operation_id="listPlans",
    responses=problem_response_docs(401, 422),
)
async def list_active_plans(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> PlanVersionList:
    """List active plan versions."""
    active = await store.get_all_active(db)
    items = active[offset: offset + limit]
    total = len(active)
    return PlanVersionList(
        items=items,
        page=collection_page(offset=offset, limit=limit, total=total),
    )


@router.post(
    "",
    response_model=PlanVersionResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createPlanVersion",
    responses=problem_response_docs(401, 409, 422),
)
async def create_plan(
    body: PlanCreateRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> PlanVersionResponse:
    """Persist a new plan version from YAML content."""
    result = engine.validate_yaml(body.yaml)
    if not result.is_valid or result.parsed is None:
        return problem_response(
            request,
            status_code=422,
            code="validation_failed",
            detail="Plan validation failed",
        )  # type: ignore[return-value]

    parsed = result.parsed
    plan_id = parsed["plan_id"]
    content_hash = engine.content_hash(body.yaml)
    next_version = await store.get_next_version(db, plan_id)
    try:
        plan_version = await store.store_version(
            db,
            plan_id=plan_id,
            version=next_version,
            content_hash=content_hash,
            content=parsed,
            retention_class=parsed.get("retention_class", "standard"),
            git_commit_sha=body.git_commit_sha,
            validation_result={
                "is_valid": result.is_valid,
                "errors": result.errors,
                "warnings": result.warnings,
            },
            created_by=current_user.username,
        )
        if body.activate:
            await store.activate(db, plan_version.id, activated_by=current_user.username)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        return problem_response(
            request,
            status_code=409,
            code="conflict",
            detail="A conflicting plan version already exists",
        )  # type: ignore[return-value]

    response.headers["Location"] = f"/api/v1/plans/{plan_id}/versions/{plan_version.id}"
    return plan_version  # type: ignore[return-value]


@router.get(
    "/{plan_id}/active-version",
    response_model=PlanVersionResponse,
    operation_id="getActivePlanVersion",
    responses=problem_response_docs(401, 404, 422),
)
async def get_active_plan(
    plan_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> PlanVersionResponse:
    """Return the active plan version."""
    active = await store.get_active(db, plan_id)
    if active is None:
        return problem_response(
            request,
            status_code=404,
            code="not_found",
            detail=f"No active plan found for '{plan_id}'",
        )  # type: ignore[return-value]
    return active  # type: ignore[return-value]


@router.patch(
    "/{plan_id}/active-version",
    response_model=PlanVersionResponse,
    operation_id="updateActivePlanVersion",
    responses=problem_response_docs(401, 404, 409, 422),
)
async def update_active_plan(
    plan_id: str,
    body: PlanActivationRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> PlanVersionResponse:
    """Activate a specific version or roll back to the previous version."""
    if body.rollback:
        activated = await store.rollback(db, plan_id, activated_by=current_user.username)
    else:
        version_id = body.version_id
        assert version_id is not None
        activated = await store.activate(db, version_id, activated_by=current_user.username)
        if activated is not None and activated.plan_id != plan_id:
            return problem_response(
                request,
                status_code=409,
                code="conflict",
                detail="Requested version does not belong to the target plan",
            )  # type: ignore[return-value]

    if activated is None:
        return problem_response(
            request,
            status_code=404,
            code="not_found",
            detail=f"No matching plan version found for '{plan_id}'",
        )  # type: ignore[return-value]

    await db.commit()
    return activated  # type: ignore[return-value]


@router.get(
    "/{plan_id}/versions",
    response_model=PlanVersionList,
    operation_id="listPlanVersions",
    responses=problem_response_docs(401, 422),
)
async def list_plan_versions(
    plan_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> PlanVersionList:
    """List all stored versions for a plan, newest first."""
    versions = await store.get_versions(db, plan_id, limit=limit, offset=offset)
    return PlanVersionList(
        items=versions,
        page=collection_page(offset=offset, limit=limit, total=offset + len(versions)),
    )


@router.get(
    "/{plan_id}/versions/{version_id}",
    response_model=PlanVersionResponse,
    operation_id="getPlanVersion",
    responses=problem_response_docs(401, 404, 422),
)
async def get_plan_version(
    plan_id: str,
    version_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> PlanVersionResponse:
    """Get a specific stored plan version."""
    versions = await store.get_versions(db, plan_id, limit=200, offset=0)
    for version in versions:
        if version.id == version_id:
            return version  # type: ignore[return-value]

    return problem_response(
        request,
        status_code=404,
        code="not_found",
        detail=f"Plan version '{version_id}' not found",
    )  # type: ignore[return-value]


@router.post(
    ":sync-from-disk",
    response_model=PlanVersionList,
    operation_id="syncPlansFromDisk",
    responses=problem_response_docs(401, 409, 422),
)
async def sync_plans_from_disk(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> PlanVersionList:
    """Reload plan files from disk and activate any changed versions."""
    plan_dir = Path(settings.plan_dir)
    if not plan_dir.is_dir():
        return problem_response(
            request,
            status_code=422,
            code="validation_failed",
            detail=f"Plan directory not found: {plan_dir}",
        )  # type: ignore[return-value]

    synced: list[PlanVersion] = []

    for plan_file in sorted(plan_dir.glob("*.yaml")):
        raw = plan_file.read_text(encoding="utf-8")
        result = engine.validate_yaml(raw)
        if not result.is_valid or result.parsed is None:
            continue

        parsed = result.parsed
        plan_id = parsed["plan_id"]
        next_version = await store.get_next_version(db, plan_id)
        plan_version = await store.store_version(
            db,
            plan_id=plan_id,
            version=next_version,
            content_hash=engine.content_hash(raw),
            content=parsed,
            retention_class=parsed.get("retention_class", "standard"),
            validation_result={
                "is_valid": result.is_valid,
                "errors": result.errors,
                "warnings": result.warnings,
            },
            created_by=current_user.username,
        )
        await store.activate(db, plan_version.id, activated_by=current_user.username)
        synced.append(plan_version)

    await db.commit()
    logger.info("plans_synced", synced_count=len(synced))
    return PlanVersionList(
        items=synced,
        page=collection_page(offset=0, limit=len(synced) or 1, total=len(synced)),
    )
