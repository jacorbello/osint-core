"""Async database engine and session factory."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from osint_core.config import settings

engine = create_async_engine(settings.database_url, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def reinitialize_engine() -> None:
    """Recreate the engine and session factory in the current process.

    Call this after a fork (e.g. in a Celery worker_process_init signal handler)
    to avoid inheriting a connection pool bound to the parent's event loop.
    """
    global engine, async_session  # noqa: PLW0603
    engine = create_async_engine(settings.database_url, echo=False)
    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
