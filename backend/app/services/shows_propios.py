"""Reglas de los shows propios de un hotel (ver models/show_propio)."""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Booking
from app.models.enums import BookingStatus
from app.models.show_propio import ShowPropio


async def es_propio(db: AsyncSession, company_id: int | None, show_id: int | None) -> bool:
    if not company_id or not show_id:
        return False
    return (await db.scalar(
        select(ShowPropio.id).where(ShowPropio.company_id == company_id,
                                    ShowPropio.show_id == show_id))) is not None


async def aplicar(db: AsyncSession, booking: Booking) -> None:
    """Al crear una actuación: si es un show propio de ese hotel, sin fee."""
    if await es_propio(db, booking.company_id, booking.show_id):
        booking.show_propio = True
        booking.commission_pct = 0


async def marcar(db: AsyncSession, *, company_id: int, show_id: int, artist_id: int | None,
                 origen: str, invitacion_id: int | None = None,
                 user_id: int | None = None) -> ShowPropio:
    """Registra el show propio (si no lo era ya) y lo aplica a las actuaciones
    de ese show con ese hotel que todavía no se han facturado ni cerrado."""
    sp = (await db.execute(select(ShowPropio).where(
        ShowPropio.company_id == company_id, ShowPropio.show_id == show_id))).scalar_one_or_none()
    if sp is None:
        sp = ShowPropio(company_id=company_id, show_id=show_id, artist_id=artist_id,
                        origen=origen, invitacion_id=invitacion_id, creado_por_user_id=user_id)
        db.add(sp)
        await db.flush()
    await db.execute(
        update(Booking)
        .where(Booking.company_id == company_id, Booking.show_id == show_id,
               Booking.cfdi_id.is_(None),
               Booking.status.in_((BookingStatus.PENDING, BookingStatus.CONFIRMED)))
        .values(show_propio=True, commission_pct=0)
    )
    return sp
