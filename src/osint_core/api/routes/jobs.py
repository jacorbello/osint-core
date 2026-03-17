"""Job API routes."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from osint_core.api.deps import get_current_user, get_db
from osint_core.api.errors import collection_page, problem_response, problem_response_docs
from osint_core.api.middleware.auth import UserInfo
from osint_core.config import settings
from osint_core.models.brief import Brief
from osint_core.models.job import Job
from osint_core.schemas.job import JobCreateRequest, JobKindEnum, JobList, JobResponse
from osint_core.services.brief_generator import BriefGenerator
from osint_core.workers.ingest import ingest_source
from osint_core.workers.score import rescore_all_events_task

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def _missing_inputs(payload: dict[str, object], *required_keys: str) -> list[str]:
    """Return missing required input keys."""
    missing = [key for key in required_keys if payload.get(key) in (None, "")]
    return missing


@router.post(
    "",
    response_model=JobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="createJob",
    responses=problem_response_docs(401, 409, 422, 503),
)
async def create_job(
    body: JobCreateRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> Job:
    """Create and dispatch a new asynchronous platform job."""
    if body.idempotency_key:
        result = await db.execute(
            select(Job).where(Job.idempotency_key == body.idempotency_key).limit(1)
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            response.status_code = status.HTTP_200_OK
            response.headers["Location"] = f"/api/v1/jobs/{existing.id}"
            return existing

    input_payload = body.input

    if body.kind == JobKindEnum.ingest:
        missing = _missing_inputs(input_payload, "source_id", "plan_id")
        if missing:
            return problem_response(
                request,
                status_code=422,
                code="validation_failed",
                detail=f"Missing required job input fields: {', '.join(missing)}",
            )  # type: ignore[return-value]
        task = ingest_source.delay(
            str(input_payload["source_id"]),
            str(input_payload["plan_id"]),
        )
        job = Job(
            job_type=body.kind,
            status="queued",
            celery_task_id=task.id,
            input_params=input_payload,
            idempotency_key=body.idempotency_key,
        )
    elif body.kind == JobKindEnum.rescore:
        task = rescore_all_events_task.delay(input_payload.get("plan_id"))
        job = Job(
            job_type=body.kind,
            status="queued",
            celery_task_id=task.id,
            input_params=input_payload,
            idempotency_key=body.idempotency_key,
        )
    elif body.kind == JobKindEnum.brief_generate:
        missing = _missing_inputs(input_payload, "query")
        if missing:
            return problem_response(
                request,
                status_code=422,
                code="validation_failed",
                detail=f"Missing required job input fields: {', '.join(missing)}",
            )  # type: ignore[return-value]
        generator = BriefGenerator(
            ollama_url=settings.ollama_url,
            ollama_model=settings.ollama_model,
        )
        job = Job(
            job_type=body.kind,
            status="running",
            input_params=input_payload,
            idempotency_key=body.idempotency_key,
        )
        db.add(job)
        await db.flush()
        try:
            content_md = await generator.generate(
                query=str(input_payload["query"]),
                events=[],
                indicators=[],
                entities=[],
            )
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
            await db.commit()
            return problem_response(
                request,
                status_code=503,
                code="dependency_unavailable",
                detail="Brief generation failed",
            )  # type: ignore[return-value]

        brief = Brief(
            title=str(input_payload["query"]),
            content_md=content_md,
            target_query=str(input_payload["query"]),
            generated_by="ollama",
            model_id=settings.ollama_model,
            requested_by=current_user.username,
        )
        db.add(brief)
        await db.flush()
        job.status = "succeeded"
        job.output = {"brief_id": str(brief.id)}
        await db.commit()
        await db.refresh(job)
        response.headers["Location"] = f"/api/v1/jobs/{job.id}"
        return job
    else:
        return problem_response(
            request,
            status_code=422,
            code="validation_failed",
            detail=f"Unsupported job kind '{body.kind}'",
        )  # type: ignore[return-value]

    db.add(job)
    await db.commit()
    await db.refresh(job)
    response.headers["Location"] = f"/api/v1/jobs/{job.id}"
    return job


@router.get(
    "",
    response_model=JobList,
    operation_id="listJobs",
    responses=problem_response_docs(401, 422),
)
async def list_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    kind: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> JobList:
    """List jobs with optional filters."""
    stmt = select(Job)
    count_stmt = select(func.count()).select_from(Job)

    if status is not None:
        stmt = stmt.where(Job.status == status)
        count_stmt = count_stmt.where(Job.status == status)
    if kind is not None:
        stmt = stmt.where(Job.job_type == kind)
        count_stmt = count_stmt.where(Job.job_type == kind)

    stmt = stmt.order_by(Job.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(stmt)
    items = list(result.scalars().all())

    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    return JobList(items=items, page=collection_page(offset=offset, limit=limit, total=total))


@router.get(
    "/{job_id}",
    response_model=JobResponse,
    operation_id="getJob",
    responses=problem_response_docs(401, 404, 422),
)
async def get_job(
    job_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> JobResponse:
    """Get a single job by ID."""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        return problem_response(
            request,
            status_code=404,
            code="not_found",
            detail="Job not found",
        )  # type: ignore[return-value]
    return job  # type: ignore[return-value]
