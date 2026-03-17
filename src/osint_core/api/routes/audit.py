"""Audit log API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from osint_core.api.deps import get_current_user, get_db
from osint_core.api.errors import collection_page, problem_response_docs
from osint_core.api.middleware.auth import UserInfo
from osint_core.schemas.audit import AuditLogList
from osint_core.services.audit import list_audit_entries

router = APIRouter(prefix="/api/v1/audit", tags=["audit"])


@router.get(
    "",
    response_model=AuditLogList,
    operation_id="listAuditEntries",
    responses=problem_response_docs(401, 422),
)
async def list_audit(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    action: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_user: UserInfo = Depends(get_current_user),
) -> AuditLogList:
    """List audit log entries with optional action filter."""
    entries, total = await list_audit_entries(
        db, limit=limit, offset=offset, action=action
    )

    return AuditLogList(items=entries, page=collection_page(offset=offset, limit=limit, total=total))
