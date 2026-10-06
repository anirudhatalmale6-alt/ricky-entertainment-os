"""La línea de tiempo de una orden de actuación.

Se arma con DOS fuentes y eso es a propósito:

1. La BITÁCORA (``booking_eventos``), que se escribe de aquí en adelante. Es la
   única que puede contar los CAMBIOS: que alguien movió la hora, que subió el
   precio, que se cambió de salón. Eso no deja rastro en ninguna columna.

2. Las COLUMNAS que la orden ya tenía: ``created_at``, ``notified_at``,
   ``confirmed_at``, ``llegada_at``, ``incidencia_at``, ``cancelled_at``, más la
   fecha de la reseña y la del CFDI.

La fuente 2 existe porque sin ella las 773 órdenes del demo y las 184 de
producción tendrían la bitácora vacía, y una línea de tiempo que empieza a
contar el día que la programamos no sirve para auditar nada. Con esto, una orden
de agosto enseña su historia completa desde el primer día.

Cuando las dos fuentes cuentan lo mismo (el alta, la confirmación), MANDA LA
BITÁCORA: tiene el actor y el detalle, la columna sólo tiene la hora.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking_evento import BookingEvento

# Los tipos. El orden de esta lista no importa; el de la línea de tiempo lo da
# la hora, siempre, porque es lo único que no se puede discutir.
CREADA = "creada"
ENVIADA = "enviada"
ACEPTADA = "aceptada"
RECHAZADA = "rechazada"
CAMBIO = "cambio"
LLEGADA = "llegada"
CALIFICADA = "calificada"
INCIDENCIA = "incidencia"
CANCELADA = "cancelada"
FACTURADA = "facturada"
PAGADA = "pagada"

# Cómo se pinta cada uno. Va en el servidor para que no haya dos listas.
ICONO = {
    CREADA: ("📋", "neutro"), ENVIADA: ("📨", "neutro"),
    ACEPTADA: ("✓", "bien"), RECHAZADA: ("✕", "mal"),
    CAMBIO: ("✎", "aviso"), LLEGADA: ("📍", "bien"),
    CALIFICADA: ("★", "bien"), INCIDENCIA: ("⚠", "mal"),
    CANCELADA: ("✕", "mal"), FACTURADA: ("🧾", "neutro"),
    PAGADA: ("💰", "bien"),
}

ROLES = {"hotel": "Hotel", "proveedor": "Proveedor", "seguridad": "Seguridad",
         "showma": "SHOWMA", "sistema": "Sistema"}


def quien(scope) -> tuple[int | None, str | None, str]:
    """(id, nombre, rol) de quien está haciendo la acción.

    Se resuelve del scope y no se pide por parámetro para que ningún endpoint
    pueda apuntar la acción a nombre de otro por descuido.
    """
    if scope is None:
        return None, None, "sistema"
    usuario = getattr(scope, "user", None)
    uid = getattr(usuario, "id", None)
    nombre = getattr(usuario, "full_name", None)
    if getattr(scope, "is_admin", False):
        rol = "showma"
    elif getattr(scope, "is_artist", False):
        rol = "proveedor"
    elif getattr(scope, "company_id", None) or getattr(scope, "group_id", None):
        rol = "hotel"
    else:
        rol = "sistema"
    return uid, nombre, rol


def registrar(db: AsyncSession, booking, tipo: str, texto: str, *,
              scope=None, detalle: str | None = None,
              actor_nombre: str | None = None, actor_rol: str | None = None) -> None:
    """Apunta un evento. NO hace commit: se queda en la misma transacción que el
    cambio que lo provoca, para que no pueda existir uno sin el otro."""
    uid, nombre, rol = quien(scope)
    db.add(BookingEvento(
        booking_id=booking.id if hasattr(booking, "id") else booking,
        tipo=tipo, texto=texto[:300], detalle=detalle,
        actor_id=uid, actor_nombre=(actor_nombre or nombre), actor_rol=(actor_rol or rol),
    ))


def diferencias(antes: dict, despues: dict) -> list[str]:
    """Qué cambió, en castellano, para el texto del evento.

    Sólo mira los campos que le importan a alguien que audita: fecha, hora,
    salón, precio y número de integrantes. Que cambie una nota interna no es un
    cambio que haya que justificarle a un contador.
    """
    etiquetas = [
        ("starts_at", "la fecha y hora"),
        ("ends_at", "la hora de fin"),
        ("venue_id", "el salón"),
        ("agreed_price", "el precio"),
        ("event_type", "el tipo de evento"),
    ]
    out = []
    for campo, etiqueta in etiquetas:
        if campo not in despues:
            continue
        a, d = antes.get(campo), despues.get(campo)
        if a == d:
            continue
        out.append(etiqueta)
    return out


def _fmt(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


async def linea_de_tiempo(db: AsyncSession, booking) -> list[dict]:
    """Todo lo que le pasó a esta orden, de lo más viejo a lo más nuevo."""
    from app.models.cfdi import Cfdi
    from app.models.review import Review

    eventos: list[dict] = []

    def add(cuando, tipo, texto, *, detalle=None, actor=None, rol=None, origen="columna"):
        if not cuando:
            return
        icono, color = ICONO.get(tipo, ("•", "neutro"))
        eventos.append({
            "cuando": _fmt(cuando), "tipo": tipo, "texto": texto, "detalle": detalle,
            "actor": actor, "rol": rol, "rol_texto": ROLES.get(rol or "", None),
            "icono": icono, "color": color, "origen": origen,
        })

    # --- 1. Lo que ya estaba en las columnas de la orden -------------------
    add(booking.created_at, CREADA,
        f"Orden emitida{(' · ' + booking.folio) if booking.folio else ''}")
    add(booking.notified_at, ENVIADA, "Enviada al proveedor")
    add(booking.confirmed_at, ACEPTADA, "El proveedor aceptó la actuación")
    if booking.llegada_at:
        add(booking.llegada_at, LLEGADA,
            "Llegada confirmada en el acceso",
            detalle=(f"La registró {booking.llegada_por}" if booking.llegada_por else None),
            actor=booking.llegada_por, rol="seguridad")
    if booking.incidencia_at:
        from app.api.v1.reviews import _GRUPO, _TEXTO, culpa_del_proveedor
        motivo = booking.incidencia_motivo
        add(booking.incidencia_at, INCIDENCIA,
            f"No se completó: {_TEXTO.get(motivo, motivo or '—')}",
            detalle=booking.incidencia_nota,
            rol="hotel")
        eventos[-1]["cuenta_al_proveedor"] = culpa_del_proveedor(motivo)
        eventos[-1]["grupo"] = _GRUPO.get(motivo or "")
    if booking.cancelled_at:
        quien_txt = {"hotel": "el hotel", "artist": "el proveedor",
                     "admin": "SHOWMA"}.get(booking.cancelled_by or "", "")
        add(booking.cancelled_at, CANCELADA,
            f"Cancelada{(' por ' + quien_txt) if quien_txt else ''}",
            detalle=booking.cancellation_reason, rol=booking.cancelled_by)

    reseña = (await db.execute(
        select(Review).where(Review.booking_id == booking.id))).scalar_one_or_none()
    if reseña is not None:
        add(reseña.created_at, CALIFICADA,
            f"Calificada con {reseña.rating} de 5 · confirma que ocurrió y libera el cobro",
            detalle=reseña.comment,
            actor=reseña.author_name, rol="hotel")

    if booking.cfdi_id:
        cfdi = await db.get(Cfdi, booking.cfdi_id)
        if cfdi is not None:
            add(cfdi.stamped_at or cfdi.created_at, FACTURADA,
                f"Incluida en la factura{(' ' + cfdi.folio) if cfdi.folio else ''}",
                detalle=(f"Folio fiscal {cfdi.uuid}" if cfdi.uuid else None),
                rol="showma")

    # --- 2. La bitácora, que es la única que cuenta los cambios -----------
    filas = list((await db.execute(
        select(BookingEvento).where(BookingEvento.booking_id == booking.id)
        .order_by(BookingEvento.created_at))).scalars().all())
    tipos_en_bitacora = {f.tipo for f in filas}
    for f in filas:
        icono, color = ICONO.get(f.tipo, ("•", "neutro"))
        eventos.append({
            "cuando": _fmt(f.created_at), "tipo": f.tipo, "texto": f.texto,
            "detalle": f.detalle, "actor": f.actor_nombre, "rol": f.actor_rol,
            "rol_texto": ROLES.get(f.actor_rol or "", None),
            "icono": icono, "color": color, "origen": "bitacora",
        })

    # Donde las dos fuentes cuentan lo mismo, manda la bitácora: trae el actor.
    # Los CAMBIOS nunca se duplican porque no hay columna que los guarde.
    eventos = [e for e in eventos
               if e["origen"] == "bitacora" or e["tipo"] not in tipos_en_bitacora]

    eventos.sort(key=lambda e: (e["cuando"] or "", e["tipo"]))
    return eventos
