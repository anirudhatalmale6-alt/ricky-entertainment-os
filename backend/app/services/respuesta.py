"""Aceptar o rechazar una actuación: UNA sola implementación.

David, 08/10: quiere que el proveedor pueda contestar desde el correo, sin
entrar a su perfil. Eso da dos caminos para la misma decisión (el botón del
panel y el enlace del correo), y dos caminos que hacen "lo mismo" acaban
haciendo cosas distintas. Ya nos pasó con el precio: el catálogo lo calculaba
por su cuenta y el cobro por la suya, y decían números distintos.

Así que la decisión vive aquí y los dos endpoints la llaman.

Sobre la seguridad del enlace, que es lo que preocupa de verdad:

  - El token es aleatorio de 128 bits y es DISTINTO del pase. Quien escanea un
    pase en una caseta no puede, con eso, comprometer una fecha y un importe.
  - Abrir el enlace NO hace nada. Sólo pinta la página. Lo que acepta es el
    POST del botón. Es deliberado: los filtros de correo abren los enlaces de
    los mensajes entrantes para analizarlos, y si el GET aceptara, la actuación
    quedaría aceptada por un antivirus antes de que el músico la viera. Nos pasó
    con los enlaces de activación de Mailgun el 07/10.
  - Sólo funciona mientras está PENDIENTE. Volver a pulsar no vuelve a cambiar
    nada ni rompe: contesta qué pasó ya.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Booking
from app.models.enums import BookingStatus


def _ahora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def por_token(db: AsyncSession, token: str) -> Booking | None:
    if not token or len(token) < 16:
        return None
    return (await db.execute(
        select(Booking).where(Booking.respuesta_token == token))).scalar_one_or_none()


def puede_contestar(booking: Booking) -> tuple[bool, str]:
    """(se puede, por qué no). El motivo es para enseñárselo a la persona."""
    estado = booking.status.value if hasattr(booking.status, "value") else str(booking.status)
    if estado == "pending":
        return True, ""
    if estado == "confirmed":
        return False, "Esta actuación ya la aceptaste."
    if estado == "cancelled":
        return False, "Esta actuación está cancelada."
    if estado == "completed":
        return False, "Esta actuación ya se realizó."
    if estado == "no_show":
        return False, "Esta actuación quedó marcada como no completada."
    return False, "Esta actuación ya no admite respuesta."


async def aceptar(db: AsyncSession, booking: Booking, *, origen: str = "correo") -> None:
    """La acepta. `origen` sólo sirve para dejarlo escrito en el historial."""
    from app.services import historial

    booking.status = BookingStatus.CONFIRMED
    booking.confirmed_at = _ahora()
    historial.registrar(
        db, booking, historial.ACEPTADA,
        "El proveedor acepto la actuacion"
        + (" desde el correo" if origen == "correo" else ""),
        actor_rol="proveedor")


async def rechazar(db: AsyncSession, booking: Booking, *, origen: str = "correo",
                   motivo: str | None = None) -> None:
    """La rechaza.

    `cancelled_by` se queda en "artist" aunque conteste la productora: para el
    hotel el que se cayó es el lado del proveedor, y de ese campo cuelgan su
    aviso y el historial de cumplimiento.
    """
    from app.services import historial

    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = _ahora()
    booking.cancellation_reason = (motivo or "Rechazada por el proveedor").strip()[:255]
    booking.cancelled_by = "artist"
    historial.registrar(
        db, booking, historial.RECHAZADA,
        "El proveedor rechazo la actuacion"
        + (" desde el correo" if origen == "correo" else ""),
        detalle=motivo, actor_rol="proveedor")


async def datos_para_pantalla(db: AsyncSession, booking: Booking) -> dict:
    """Lo que se le enseña a quien abre el enlace.

    Enseña el IMPORTE, a diferencia del pase: aquí quien mira es el proveedor
    decidiendo si acepta, y el precio es justo lo que necesita para decidir. En
    el pase no va porque ahí quien mira es un vigilante.
    """
    from app.models.artist import Artist
    from app.models.company import Company
    from app.models.show import Show
    from app.models.venue import Venue

    show = await db.get(Show, booking.show_id) if booking.show_id else None
    venue = await db.get(Venue, booking.venue_id) if booking.venue_id else None
    empresa = await db.get(Company, booking.company_id) if booking.company_id else None
    artista = await db.get(Artist, booking.artist_id) if booking.artist_id else None

    abierta, motivo = puede_contestar(booking)
    # Un musico de productora no ve importes: cobra su empresa (David, 02/09).
    oculta_precio = bool(artista and artista.parent_id)
    return {
        "folio": booking.folio,
        "artista": artista.stage_name if artista else None,
        "show": show.show_name if show else None,
        "hotel": empresa.name if empresa else None,
        "salon": venue.name if venue else None,
        "cuando": booking.starts_at.isoformat() if booking.starts_at else None,
        "termina": booking.ends_at.isoformat() if booking.ends_at else None,
        "integrantes": getattr(show, "members", None),
        "importe": (None if oculta_precio or booking.agreed_price is None
                    else float(booking.agreed_price)),
        "moneda": booking.currency or "MXN",
        "estado": booking.status.value if hasattr(booking.status, "value") else str(booking.status),
        "puede_contestar": abierta,
        "motivo": motivo,
    }
