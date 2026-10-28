"""Contrataciones de varias fechas tratadas como UNA (David, 28/10).

Un hotel programó 23 fechas del mismo show de una vez y al proveedor no le
llegó nada: las 23 quedaron pendientes, cada una había que aceptarla aparte y
cada aceptación mandaba su propio correo con su propio QR. David: "no se me
ocurre cómo manejar lo del QR de acceso... ¿dejar un QR para todas las fechas?"

Así que todas las fechas de una tanda comparten `Booking.serie`, y eso sirve
para tres cosas:
  - un solo aviso al proveedor con la lista de fechas;
  - aceptarlas (o rechazarlas) todas de una vez, desde el panel o el correo;
  - un PASE DE TEMPORADA: un QR que en la puerta enseña la actuación de ESE día.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Booking
from app.models.enums import BookingStatus


def _estado(b: Booking) -> str:
    return b.status.value if hasattr(b.status, "value") else str(b.status)


def _naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


async def de_la_serie(db: AsyncSession, serie: str | None) -> list[Booking]:
    """Todas las fechas de la tanda, de la primera a la última."""
    if not serie or len(serie) < 16:
        return []
    return list((await db.execute(
        select(Booking).where(Booking.serie == serie).order_by(Booking.starts_at, Booking.id)
    )).scalars().all())


async def hermanas(db: AsyncSession, booking: Booking) -> list[Booking]:
    """La tanda a la que pertenece una actuación (ella incluida). Sin tanda, sólo ella."""
    if not booking.serie:
        return [booking]
    return await de_la_serie(db, booking.serie) or [booking]


def pendientes(fechas: list[Booking]) -> list[Booking]:
    return [b for b in fechas if _estado(b) == "pending"]


def la_de_hoy(fechas: list[Booking], ahora: datetime) -> tuple[Booking | None, int]:
    """La actuación que corresponde enseñar al escanear el pase de temporada.

    Hoy si hay una (la que aún no ha terminado, o la última del día); si no, la
    próxima; si ya no queda ninguna, la última. Las canceladas no cuentan salvo
    que no haya otra cosa que enseñar. Devuelve también su posición (1..n).
    """
    vivas = [b for b in fechas if _estado(b) != "cancelled"] or fechas
    if not vivas:
        return None, 0
    hoy = ahora.date()
    de_hoy = [b for b in vivas if b.starts_at and _naive(b.starts_at).date() == hoy]
    if de_hoy:
        # Si hay dos el mismo día, la que todavía no termina (con 2 h de margen).
        elegida = next((b for b in de_hoy
                        if (_naive(b.ends_at) or _naive(b.starts_at)) + timedelta(hours=2) >= ahora),
                       de_hoy[-1])
    else:
        futuras = [b for b in vivas if b.starts_at and _naive(b.starts_at) > ahora]
        elegida = futuras[0] if futuras else vivas[-1]
    return elegida, fechas.index(elegida) + 1


def resumen(fechas: list[Booking]) -> dict:
    """Primera y última fecha, cuántas y el importe total (para avisos y pantallas)."""
    con_fecha = [b for b in fechas if b.starts_at]
    return {
        "total": len(fechas),
        "desde": _naive(con_fecha[0].starts_at) if con_fecha else None,
        "hasta": _naive(con_fecha[-1].starts_at) if con_fecha else None,
        "importe": round(sum(float(b.agreed_price or 0) for b in fechas), 2),
        "fechas": [_naive(b.starts_at) for b in con_fecha],
    }


async def correo_pase_temporada(db: AsyncSession, fechas: list[Booking]) -> list:
    """UN correo con UN QR para todas las fechas confirmadas de la tanda.

    El QR lleva el token de la serie: en la puerta, /pase/<serie> resuelve la
    actuación de ese día (ver main.pase_publico).
    """
    from app.core.config import settings
    from app.models.artist import Artist
    from app.models.company import Company
    from app.models.show import Show
    from app.models.venue import Venue
    from app.services import avisos, pase as pase_svc

    confirmadas = [b for b in fechas if _estado(b) == "confirmed"]
    if not confirmadas or not confirmadas[0].serie:
        return []
    p = confirmadas[0]
    artista = await db.get(Artist, p.artist_id) if p.artist_id else None
    destino = await avisos.correo_artista(db, artista) if artista else None
    if not destino:
        return []
    show = await db.get(Show, p.show_id) if p.show_id else None
    venue = await db.get(Venue, p.venue_id) if p.venue_id else None
    empresa = await db.get(Company, p.company_id) if p.company_id else None
    url = pase_svc.url_pase(p.serie, settings.public_root)
    asunto, texto, html = avisos.pase_actuacion(
        show=(show.show_name if show else None) or "tu actuación",
        artista=(artista.stage_name or "") if artista else "",
        venue=(venue.name if venue else "") or "",
        hotel=(empresa.name if empresa else "") or "",
        cuando=p.starts_at, folio=p.folio,
        integrantes=getattr(show, "members", None), url_pase=url,
        fechas=[(_naive(b.starts_at), _naive(b.ends_at)) for b in confirmadas])
    return [avisos.Aviso(to=destino, subject=asunto, text=texto, html=html,
                         imagenes={"qrpase": pase_svc.png_qr(url, escala=6)})]


async def correo_rechazo_hotel(db: AsyncSession, rechazadas: list[Booking], motivo: str) -> list:
    """Al hotel, UN aviso de que el proveedor no puede esas fechas."""
    from app.models.artist import Artist
    from app.models.show import Show
    from app.models.venue import Venue
    from app.services import avisos

    if not rechazadas:
        return []
    p = rechazadas[0]
    show = await db.get(Show, p.show_id) if p.show_id else None
    venue = await db.get(Venue, p.venue_id) if p.venue_id else None
    artista = await db.get(Artist, p.artist_id) if p.artist_id else None
    n = len(rechazadas)
    if n > 1:
        r = resumen(rechazadas)
        motivo = (f"{motivo}. Son {n} fechas, del {r['desde']:%d/%m/%Y} al {r['hasta']:%d/%m/%Y}: "
                  "quedan libres para buscar a otro proveedor.")
    asunto, texto, html = avisos.cancelacion_musico(
        show=(show.show_name if show else None) or "la actuación",
        artista=(artista.stage_name if artista else None) or "El artista",
        venue=(venue.name if venue else "") or "",
        cuando=p.starts_at, motivo=motivo)
    return [avisos.Aviso(to=d, subject=asunto, text=texto, html=html)
            for d in await avisos.correos_hotel(db, p.company_id)]
