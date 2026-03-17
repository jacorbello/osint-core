"""Plan store — persists and retrieves versioned intelligence collection plans."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from osint_core.models.plan import PlanVersion

logger = structlog.get_logger()


class PlanStore:
    """Service layer for plan version CRUD via async SQLAlchemy sessions.

    Methods do NOT commit — callers are responsible for committing the session
    after all operations in a logical unit of work are complete.
    """

    async def store_version(
        self,
        db: AsyncSession,
        *,
        plan_id: str,
        version: int,
        content_hash: str,
        content: dict[str, Any],
        retention_class: str,
        git_commit_sha: str | None = None,
        validation_result: dict[str, Any] | None = None,
        created_by: str = "system",
    ) -> PlanVersion:
        """Store a new plan version in the database.

        Returns the newly created PlanVersion row.  Caller must commit.
        """
        plan = PlanVersion(
            plan_id=plan_id,
            version=version,
            content_hash=content_hash,
            content=content,
            retention_class=retention_class,
            git_commit_sha=git_commit_sha,
            validation_result=validation_result,
            activated_by=created_by,
        )
        db.add(plan)
        await db.flush()
        logger.info(
            "plan_version_stored",
            plan_id=plan_id,
            version=version,
            content_hash=content_hash[:12],
        )
        return plan

    async def get_all_active(self, db: AsyncSession) -> list[PlanVersion]:
        """Return all currently active plan versions."""
        stmt = (
            select(PlanVersion)
            .where(PlanVersion.is_active.is_(True))
            .order_by(PlanVersion.plan_id, PlanVersion.version)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_active(self, db: AsyncSession, plan_id: str) -> PlanVersion | None:
        """Return the currently active version of a plan, or None."""
        stmt = (
            select(PlanVersion)
            .where(PlanVersion.plan_id == plan_id, PlanVersion.is_active.is_(True))
            .limit(1)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_versions(
        self,
        db: AsyncSession,
        plan_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PlanVersion]:
        """Return all stored versions for a plan, newest first."""
        stmt = (
            select(PlanVersion)
            .where(PlanVersion.plan_id == plan_id)
            .order_by(PlanVersion.version.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_version(
        self,
        db: AsyncSession,
        plan_id: str,
        version_id: UUID,
    ) -> PlanVersion | None:
        """Return a specific plan version by plan id and version UUID."""
        stmt = select(PlanVersion).where(
            PlanVersion.plan_id == plan_id,
            PlanVersion.id == version_id,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def activate(
        self,
        db: AsyncSession,
        version_id: UUID,
        *,
        activated_by: str = "system",
    ) -> PlanVersion | None:
        """Activate a specific plan version and deactivate all others for the same plan.

        Returns the activated version, or None if the version_id was not found.
        """
        # Fetch the target version
        stmt = select(PlanVersion).where(PlanVersion.id == version_id)
        result = await db.execute(stmt)
        target = result.scalar_one_or_none()
        if target is None:
            return None

        # Bulk deactivate all active versions of this plan in a single UPDATE
        await db.execute(
            update(PlanVersion)
            .where(PlanVersion.plan_id == target.plan_id, PlanVersion.is_active.is_(True))
            .values(is_active=False)
        )

        # Activate the target
        target.is_active = True
        target.activated_at = datetime.now(UTC)
        target.activated_by = activated_by
        await db.flush()

        logger.info(
            "plan_version_activated",
            plan_id=target.plan_id,
            version=target.version,
            activated_by=activated_by,
        )
        return target

    async def rollback(
        self,
        db: AsyncSession,
        plan_id: str,
        *,
        activated_by: str = "system",
    ) -> PlanVersion | None:
        """Activate the previous (second-most-recent) version of a plan.

        Returns the newly activated version, or None if no previous version exists.
        """
        # Get the two most recent versions
        stmt = (
            select(PlanVersion)
            .where(PlanVersion.plan_id == plan_id)
            .order_by(PlanVersion.version.desc())
            .limit(2)
        )
        result = await db.execute(stmt)
        versions = list(result.scalars().all())

        if len(versions) < 2:
            logger.warning("plan_rollback_no_previous", plan_id=plan_id)
            return None

        previous = versions[1]
        return await self.activate(db, previous.id, activated_by=activated_by)

    async def get_next_version(self, db: AsyncSession, plan_id: str) -> int:
        """Return the next version number for a plan (max + 1, or 1 if none exist)."""
        stmt = (
            select(PlanVersion.version)
            .where(PlanVersion.plan_id == plan_id)
            .order_by(PlanVersion.version.desc())
            .limit(1)
        )
        result = await db.execute(stmt)
        current_max = result.scalar_one_or_none()
        return (current_max or 0) + 1
