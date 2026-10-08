"""Códigos de identificación: proveedor y orden de actuación.

David, 06/10: "cada proveedor necesita un número o código de identificación para
poder rastrear sus transacciones", y "las órdenes de servicio deben generar un
código para relacionarlas con la factura global".

La única propiedad que importa aquí es que **el código no cambie nunca**. Lo
digo porque el sistema ya tenía un número que sí cambiaba: la pantalla de
Facturación del hotel armaba las facturas en el navegador y numeraba
``INV-<quincena>-<posición en la lista>``. Al entrar una actuación de otra
propiedad en esa quincena, la factura del Hotel Azul pasaba de ``-002`` a
``-003`` sin cambiar ni un peso. Un contador que anota ese folio y vuelve al día
siguiente encuentra otro hotel. Eso no es un folio, es una etiqueta.

Por eso aquí los códigos se calculan a partir de datos que NO se pueden editar,
y además se GUARDAN en su columna:

  - el id (nunca cambia, nunca se reutiliza)
  - la fecha de alta (``created_at``), que tampoco se edita

Se usa ``created_at`` y no la fecha de la actuación a propósito: una actuación
se puede reprogramar, y si el año del folio saliera de ``starts_at``, mover una
función de diciembre a enero le cambiaría el folio a un documento ya entregado
al hotel. El año de un documento es el año en que se emitió.

Que el código sea una función de datos inmutables tiene una consecuencia muy
práctica: rellenar los que faltan es idempotente. Se puede correr el relleno en
cada arranque sin miedo, porque siempre da el mismo resultado.
"""
from __future__ import annotations

from datetime import datetime

PREFIJO_PROVEEDOR = "PRV"
PREFIJO_ORDEN = "OA"      # Orden de Actuación


def codigo_proveedor(artist_id: int) -> str:
    """PRV-00014. Cinco dígitos dan para 99,999 proveedores."""
    return f"{PREFIJO_PROVEEDOR}-{int(artist_id):05d}"


def folio_orden(booking_id: int, alta: datetime | None) -> str:
    """OA-2026-00147.

    El año es el del alta de la orden, no el de la función. El número es el id,
    así que hay huecos en la serie cuando algo se borra: eso es normal en una
    serie de documentos y es infinitamente preferible a renumerar.
    """
    anio = (alta or datetime.now()).year
    return f"{PREFIJO_ORDEN}-{anio}-{int(booking_id):05d}"


async def asignar_orden(db, booking) -> str:
    """Pone el folio y el token del pase a una orden recién creada.

    Necesita el id, así que hace ``flush`` si la fila todavía no lo tiene. No
    reasigna: si ya trae folio, se respeta y punto. Ese "y punto" es la regla
    entera de este archivo.

    El token del pase va aquí mismo, en la misma función, para que no haya forma
    de crear una orden sin su QR: una orden sin pase es una orden que el de
    seguridad no puede comprobar.
    """
    if booking.id is None:
        await db.flush()
    if not getattr(booking, "pase_token", None):
        from app.services import pase
        booking.pase_token = pase.nuevo_token()
    if not getattr(booking, "respuesta_token", None):
        from app.services import pase
        booking.respuesta_token = pase.nuevo_token()
    if getattr(booking, "folio", None):
        return booking.folio
    booking.folio = folio_orden(booking.id, booking.created_at)
    return booking.folio


async def asignar_proveedor(db, artist) -> str:
    """Igual, para el alta de un proveedor."""
    if getattr(artist, "codigo", None):
        return artist.codigo
    if artist.id is None:
        await db.flush()
    artist.codigo = codigo_proveedor(artist.id)
    return artist.codigo
