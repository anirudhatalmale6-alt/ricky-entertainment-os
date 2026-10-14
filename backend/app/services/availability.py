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


def _rango(b) -> str:
    """'de 10:00 a 13:00' para un bloqueo por horas; '' si es el día entero."""
    if b.hora_desde and b.hora_hasta:
        return f"de {b.hora_desde:%H:%M} a {b.hora_hasta:%H:%M}"
    return ""


def es_dia_entero(b) -> bool:
    return not (b.hora_desde and b.hora_hasta)


def choca(b, inicio: datetime, fin: datetime | None) -> bool:
    """¿La actuación [inicio, fin) cae dentro del bloqueo?

    Día entero: sí, sin más. Por horas: sólo si se solapan. Sin hora de fin
    se toma una hora de actuación, que es lo mínimo que dura cualquier show.
    No se añade margen de traslado: lo que el músico bloquea es exactamente lo
    que no puede, y si necesita llegar con tiempo lo incluye en el rango.
    """
    if es_dia_entero(b):
        return True
    ini = _naive(inicio)
    fin = _naive(fin) if fin else ini + timedelta(hours=1)
    d = b.blocked_on
    b_ini = datetime.combine(d, b.hora_desde)
    b_fin = datetime.combine(d, b.hora_hasta)
    return ini < b_fin and fin > b_ini


async def blocked_on(db, day: date) -> dict[int, ArtistBlockedDate]:
    """{artist_id: bloqueo} de quienes bloquearon algo ese día (entero o por horas)."""
    if day is None:
        return {}
    rows = (await db.execute(
        select(ArtistBlockedDate).where(ArtistBlockedDate.blocked_on == day)
    )).scalars().all()
    return {r.artist_id: r for r in rows}


async def is_blocked(db, artist_id: int, when, ends=None) -> tuple[bool, str | None]:
    """¿El artista bloqueó la hora de esa actuación? Devuelve (sí/no, explicación).

    La explicación ya trae las horas si el bloqueo es parcial, para que el
    hotel entienda por qué no puede contratarlo a esa hora y sí a otra.
    """
    day = as_date(when)
    if day is None or artist_id is None:
        return False, None
    row = (await db.execute(
        select(ArtistBlockedDate).where(
            ArtistBlockedDate.artist_id == artist_id,
            ArtistBlockedDate.blocked_on == day,
        )
    )).scalar_one_or_none()
    if row is None:
        return False, None
    if isinstance(when, datetime) and not choca(row, when, ends):
        return False, None
    partes = [p for p in (_rango(row), row.reason) if p]
    return True, (" · ".join(partes) or None)


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
