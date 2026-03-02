"""Shared FastAPI dependencies."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from osint_core.api.middleware.auth import UserInfo, get_current_user, require_role
from osint_core.db import async_session

__all__ = ["get_db", "get_current_user", "require_role", "UserInfo"]


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session, closing it after the request."""
    async with async_session() as session:
        yield session
