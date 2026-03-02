"""Append-only audit logging service."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from osint_core.models.audit import AuditLog


async def create_audit_entry(
    db: AsyncSession,
    *,
    action: str,
    actor: str | None = None,
    actor_username: str | None = None,
    actor_roles: list[str] | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """Create an immutable audit log entry.

    The entry is added to the session and flushed (but not committed).
    The caller is responsible for committing the transaction.
    """
    entry = AuditLog(
        action=action,
        actor=actor,
        actor_username=actor_username,
        actor_roles=actor_roles,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details or {},
    )
    db.add(entry)
    await db.flush()
    return entry


async def list_audit_entries(
    db: AsyncSession,
    *,
    limit: int = 50,
    offset: int = 0,
    action: str | None = None,
) -> tuple[list[AuditLog], int]:
    """List audit log entries ordered by created_at descending.

    Returns:
        A tuple of (entries, total_count).
    """
    stmt = select(AuditLog)
    count_stmt = select(func.count()).select_from(AuditLog)

    if action is not None:
        stmt = stmt.where(AuditLog.action == action)
        count_stmt = count_stmt.where(AuditLog.action == action)

    stmt = stmt.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(stmt)
    entries = list(result.scalars().all())

    count_result = await db.execute(count_stmt)
    total = count_result.scalar_one()

    return entries, total
