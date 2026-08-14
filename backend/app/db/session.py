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
    ("bookings", "invoice_paid", "BOOLEAN DEFAULT 0"),
    ("bookings", "payout_paid", "BOOLEAN DEFAULT 0"),
    ("tax_figures", "iva_traslado_pct", "FLOAT DEFAULT 16"),
    ("tax_figures", "isr_variable", "BOOLEAN DEFAULT 0"),
    ("artists", "tax_figure_id", "INTEGER"),
    # CSD / facturación electrónica del músico (Facturama)
    ("artists", "csd_status", "VARCHAR(20) DEFAULT 'none'"),
    ("artists", "csd_uploaded_at", "DATE"),
    ("artists", "csd_expires_at", "DATE"),
    # Ficha de alta del prospecto (datos financieros/fiscales de la empresa)
    ("companies", "fiscal_constancia_url", "VARCHAR(500)"),
    ("companies", "bank_name", "VARCHAR(120)"),
    ("companies", "bank_clabe", "VARCHAR(20)"),
    ("companies", "preferred_currency", "VARCHAR(8) DEFAULT 'MXN'"),
    ("companies", "logo_url", "VARCHAR(500)"),          # imagen/logo de la propiedad
    # REVISION 4: cancelación por el músico + foto del venue en solicitudes
    ("bookings", "cancelled_by", "VARCHAR(16)"),         # artist | hotel | admin
    ("product_requests", "venue_photo_url", "VARCHAR(500)"),
    # Hasta 3 fotos del espacio en la solicitud (la primera es la de cabecera)
    ("product_requests", "images", "JSON"),
    # Extra por larga distancia en cada show (gasolina)
    ("shows", "travel_fee", "NUMERIC(12,2)"),
    ("shows", "travel_fee_km", "INTEGER DEFAULT 30"),
    # Fotos adjuntas en el chat
    ("messages", "images", "JSON"),
    # Facturación por quincena
    ("cfdis", "period", "VARCHAR(16)"),
    ("bookings", "cfdi_id", "INTEGER"),
    # Avisos por correo: a quién se le mandó y si salió
    ("artist_notifications", "email_to", "VARCHAR(255)"),
    ("artist_notifications", "email_sent_at", "DATETIME"),
    # Afluencia y retención de público: las dos preguntas del "Calificar"
    ("reviews", "afluencia", "VARCHAR(10)"),
    ("reviews", "retencion", "VARCHAR(10)"),
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
