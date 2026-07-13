"""Async database engine, session factory and FastAPI dependency."""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings

# For SQLite (aiosqlite) use NullPool: never keep a pooled connection around.
# Under cPanel Passenger the app is preloaded and then *forked* into workers, and
# a2wsgi runs each request on its own event loop — a pooled aiosqlite connection
# (with its background thread) would not survive the fork/loop switch and the
# first request would deadlock. NullPool opens a fresh connection per checkout,
# which is correct (and plenty fast) for this staging deploy.
_engine_kwargs: dict = {"echo": False, "future": True}
if settings.DATABASE_URL.startswith("sqlite"):
    _engine_kwargs["poolclass"] = NullPool

engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    """Create tables. For production use Alembic migrations instead."""
    from app.db.base import Base
    from app import models  # noqa: F401  (ensure models are registered)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
