"""¿Puede este artista trabajar ese día?

Dos motivos para que no: bloqueó el día en su calendario (vacaciones,
enfermedad) o ya tiene una actuación activa a esa hora. Hasta ahora sólo se
revisaba lo segundo, y sólo al guardar; el catálogo mostraba a todo el mundo
como "Disponible".
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.models.blocked_date import ArtistBlockedDate
from app.models.booking import Booking
from app.models.enums import BookingStatus

# Horas de margen entre dos actuaciones del mismo artista (traslado y montaje).
TRAVEL_BUFFER_HOURS = 1
_ACTIVE = (BookingStatus.PENDING, BookingStatus.CONFIRMED)


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def as_date(when) -> date | None:
    if when is None:
        return None
    if isinstance(when, datetime):
        return when.date()
    if isinstance(when, date):
        return when
    try:
        return datetime.fromisoformat(str(when).replace("Z", "")).date()
    except (TypeError, ValueError):
        return None


async def blocked_on(db, day: date) -> dict[int, str | None]:
    """{artist_id: motivo} de quienes bloquearon ese día."""
    if day is None:
        return {}
    rows = (await db.execute(
        select(ArtistBlockedDate.artist_id, ArtistBlockedDate.reason)
        .where(ArtistBlockedDate.blocked_on == day)
    )).all()
    return {aid: reason for aid, reason in rows}


async def is_blocked(db, artist_id: int, when) -> tuple[bool, str | None]:
    """¿El artista bloqueó el día de esa fecha? Devuelve (sí/no, motivo)."""
    day = as_date(when)
    if day is None or artist_id is None:
        return False, None
    row = (await db.execute(
        select(ArtistBlockedDate).where(
            ArtistBlockedDate.artist_id == artist_id,
            ArtistBlockedDate.blocked_on == day,
        )
    )).scalar_one_or_none()
    return (row is not None), (row.reason if row else None)


async def busy_on(db, day: date) -> tuple[dict[int, datetime], dict[int, datetime]]:
    """Quién ya trabaja ese día, por ARTISTA y por SHOW.

    Devuelve dos mapas: {artist_id: hora} y {show_id: hora}. Quien pregunta
    elige cuál mirar, y de eso depende a quién se bloquea:

      - un proveedor que actúa él mismo se mira por ARTISTA: tenga dos shows o
        diez, no puede estar en dos hoteles a la vez;
      - una productora se mira por SHOW, porque cada show suyo lo cubre gente
        distinta (David, 20/09: "una productora tiene varios shows con personas
        diferentes... nos bloquearía el resto de los músicos").

    Sirve para avisar en el catálogo; el choque real (con margen de traslado) se
    revisa a la hora de guardar, cuando ya se conoce la hora exacta.
    """
    if day is None:
        return {}, {}
    start = datetime(day.year, day.month, day.day)
    end = start + timedelta(days=1)
    rows = (await db.execute(
        select(Booking.artist_id, Booking.show_id, Booking.starts_at).where(
            Booking.status.in_(_ACTIVE),
            Booking.starts_at >= start,
            Booking.starts_at < end,
        ).order_by(Booking.starts_at)
    )).all()
    por_artista: dict[int, datetime] = {}
    por_show: dict[int, datetime] = {}
    for aid, sid, starts in rows:
        if aid is not None and aid not in por_artista:
            por_artista[aid] = _naive(starts)
        if sid is not None and sid not in por_show:
            por_show[sid] = _naive(starts)
    return por_artista, por_show
