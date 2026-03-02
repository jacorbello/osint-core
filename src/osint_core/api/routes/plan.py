"""Plan management API routes — validate, sync, activate, rollback, and version listing."""

from pathlib import Path
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from osint_core.api.deps import get_db
from osint_core.config import settings
from osint_core.schemas.plan import PlanValidationResult, PlanVersionResponse
from osint_core.services.plan_engine import PlanEngine
from osint_core.services.plan_store import PlanStore

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/plan", tags=["plan"])
engine = PlanEngine()
store = PlanStore()


@router.post("/validate", response_model=PlanValidationResult)
async def validate_plan(request: Request):
    """Validate a plan YAML payload without persisting it."""
    body = await request.body()
    result = engine.validate_yaml(body.decode())
    return {
        "is_valid": result.is_valid,
        "errors": result.errors,
        "warnings": result.warnings,
    }


@router.get("/active", response_model=PlanVersionResponse)
async def get_active_plan(
    plan_id: str = "default",
    db: AsyncSession = Depends(get_db),
):
    """Return the currently active plan version."""
    # TODO: integration test — requires running Postgres
    active = await store.get_active(db, plan_id)
    if active is None:
        raise HTTPException(status_code=404, detail=f"No active plan found for '{plan_id}'")
    return active


@router.post("/sync")
async def sync_plans(db: AsyncSession = Depends(get_db)):
    """Reload plans from disk, validate, and store new versions in the database.

    Scans ``settings.plan_dir`` for ``*.yaml`` files, validates each, and stores
    any plan whose content hash differs from the latest stored version.
    """
    # TODO: integration test — requires running Postgres and plan files on disk
    plan_dir = Path(settings.plan_dir)
    if not plan_dir.is_dir():
        raise HTTPException(status_code=400, detail=f"Plan directory not found: {plan_dir}")

    synced: list[dict] = []
    errors: list[dict] = []

    for plan_file in sorted(plan_dir.glob("*.yaml")):
        raw = plan_file.read_text(encoding="utf-8")
        result = engine.validate_yaml(raw)

        if not result.is_valid:
            errors.append({"file": plan_file.name, "errors": result.errors})
            continue

        parsed = result.parsed
        plan_id = parsed["plan_id"]
        content_hash = engine.content_hash(raw)

        # Check if this exact content already exists
        versions = await store.get_versions(db, plan_id, limit=1)
        if versions and versions[0].content_hash == content_hash:
            continue  # No change, skip

        next_version = await store.get_next_version(db, plan_id)
        plan_version = await store.store_version(
            db,
            plan_id=plan_id,
            version=next_version,
            content_hash=content_hash,
            content=parsed,
            retention_class=parsed.get("retention_class", "standard"),
            validation_result={
                "is_valid": result.is_valid,
                "errors": result.errors,
                "warnings": result.warnings,
            },
        )

        # Auto-activate new versions
        await store.activate(db, plan_version.id)
        synced.append({"plan_id": plan_id, "version": next_version})

    logger.info("plans_synced", synced_count=len(synced), error_count=len(errors))
    return {"synced": synced, "errors": errors}


@router.post("/rollback")
async def rollback_plan(
    plan_id: str = "default",
    db: AsyncSession = Depends(get_db),
):
    """Activate the previous version of a plan."""
    # TODO: integration test — requires running Postgres
    rolled_back = await store.rollback(db, plan_id)
    if rolled_back is None:
        raise HTTPException(
            status_code=404,
            detail=f"No previous version found for plan '{plan_id}'",
        )
    return {
        "plan_id": rolled_back.plan_id,
        "activated_version": rolled_back.version,
    }


@router.post("/activate/{version_id}")
async def activate_plan(
    version_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Activate a specific plan version by its UUID."""
    # TODO: integration test — requires running Postgres
    activated = await store.activate(db, version_id)
    if activated is None:
        raise HTTPException(status_code=404, detail=f"Plan version '{version_id}' not found")
    return {
        "plan_id": activated.plan_id,
        "activated_version": activated.version,
    }


@router.get("/versions", response_model=list[PlanVersionResponse])
async def list_plan_versions(
    plan_id: str = "default",
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """List all stored versions for a plan, newest first."""
    # TODO: integration test — requires running Postgres
    return await store.get_versions(db, plan_id, limit=limit, offset=offset)
