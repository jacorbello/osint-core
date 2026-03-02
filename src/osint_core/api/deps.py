"""Shared FastAPI dependencies."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from osint_core.db import async_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session, closing it after the request."""
    async with async_session() as session:
        yield session
