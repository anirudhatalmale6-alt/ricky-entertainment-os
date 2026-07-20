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


# Additive columns that landed after the initial deploy. create_all() creates
# missing TABLES but never alters existing ones, and this staging box is on
# SQLite with FTP-only access (no shell to run migrations). So we add any missing
# column here at boot — idempotent and safe (ADD COLUMN only, never drops).
_SQLITE_ADDED_COLUMNS = [
    # (table, column, sqlite column definition)
    ("artists", "auto_confirm_bookings", "BOOLEAN DEFAULT 0"),
    ("artists", "profile_image_url", "VARCHAR(500)"),
    ("request_proposals", "images", "JSON"),
    ("bookings", "notified_at", "DATETIME"),
]


def _apply_additive_columns(sync_conn) -> None:
    for table, column, decl in _SQLITE_ADDED_COLUMNS:
        cols = {row[1] for row in sync_conn.exec_driver_sql(f"PRAGMA table_info({table})")}
        if not cols:
            continue  # table doesn't exist yet (fresh DB) — create_all made it with the column
        if column not in cols:
            sync_conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            # One-time backfill (runs only the first boot after the column lands,
            # since afterwards the column already exists and we skip this branch).
            if (table, column) == ("bookings", "notified_at"):
                # Every booking that existed before the "borrador" concept was
                # already sent to its artist — mark it notified so it doesn't
                # vanish from the artist's agenda. New rows default to NULL (draft).
                sync_conn.exec_driver_sql(
                    "UPDATE bookings SET notified_at = COALESCE(confirmed_at, created_at) "
                    "WHERE notified_at IS NULL"
                )


async def init_db() -> None:
    """Create tables. For production use Alembic migrations instead."""
    from app.db.base import Base
    from app import models  # noqa: F401  (ensure models are registered)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if settings.DATABASE_URL.startswith("sqlite"):
            await conn.run_sync(_apply_additive_columns)
