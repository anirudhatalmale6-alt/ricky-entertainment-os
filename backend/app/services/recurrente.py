"""Precio recurrente: la tarifa por volumen de un show.

David, 30/09. Un hotel que programa el mismo show muchas veces merece mejor
precio, y al proveedor le conviene la fecha fija. Lo que antes era "precio
corporativo" -un campo que NADIE usaba: las 184 reservas tienen el tipo de
evento vacio- pasa a significar esto.

Las reglas son suyas, textuales:

  - Se cuenta por HOTEL y por SHOW: cinco actuaciones del mismo show
    contratadas por el mismo hotel.
  - La ventana es de 45 dias HACIA ADELANTE desde la actuacion que se agenda.
    Lo que caiga fuera no suma.
  - Si cancelan una y bajan de cinco, se vuelve al precio normal.

Y una decision que no es de negocio sino de realidad fiscal: al recalcular
solo se tocan actuaciones FUTURAS Y SIN FACTURAR. Una actuacion que ya se
toco y ya se timbro no se reprecia, porque un CFDI no se corrige: se cancela y
se emite otro, y eso ante el SAT es un tramite, no un ajuste de pantalla.

El precio se enseña ANTES, en la ficha del proveedor, para que el hotel pueda
planear las cinco de una vez. Ese es el camino normal y ahi no hay recalculo
ninguno: se aplica limpio al crearlas.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Booking
from app.models.enums import BookingStatus

# Cuantas actuaciones del mismo show activan la tarifa, y en cuantos dias.
MINIMO = 5
DIAS_VENTANA = 45


def precio_recurrente(show) -> float | None:
    """La tarifa por volumen del show, si la tiene.

    Vive en la columna que antes era price_corporate. No se renombra la columna
    a proposito: 24 shows ya la tienen cargada con un precio mas bajo que el
    normal, y una migracion para cambiarle el nombre al mismo dato solo añade
    una forma de perderlo.
    """
    v = getattr(show, "price_corporate", None)
    return float(v) if v not in (None, "") and float(v) > 0 else None


def ventana(fecha: datetime) -> tuple[datetime, datetime]:
    """Los 45 dias que cuentan, mirando hacia adelante desde esa actuacion."""
    return fecha, fecha + timedelta(days=DIAS_VENTANA)


async def fechas_vecinas(db: AsyncSession, *, show_id: int, company_id: int | None,
                         cerca_de: datetime, excluir_id: int | None = None) -> list[datetime]:
    """Las actuaciones vivas de ese show en ese hotel, alrededor de esa fecha.

    Las canceladas NO cuentan: si contaran, bastaria con agendar cinco y
    cancelar cuatro para quedarse con la tarifa de volumen.
    """
    if not company_id:
        return []
    q = (select(Booking.starts_at)
         .where(Booking.show_id == show_id,
                Booking.company_id == company_id,
                Booking.status != BookingStatus.CANCELLED,
                Booking.starts_at > cerca_de - timedelta(days=DIAS_VENTANA),
                Booking.starts_at < cerca_de + timedelta(days=DIAS_VENTANA)))
    if excluir_id:
        q = q.where(Booking.id != excluir_id)
    return sorted(r[0] for r in (await db.execute(q)).all())


def _mejor_ventana(fechas: list[datetime], incluye: datetime) -> int:
    """Cuantas actuaciones caben, como mucho, en una ventana de 45 dias que
    contenga `incluye`.

    Esto nacio de una prueba que salio mal. La primera version contaba solo
    HACIA ADELANTE desde la actuacion que se agenda, y asi la tarifa no se
    activaba NUNCA: al mirar la segunda, la primera quedaba detras de la
    ventana y no sumaba; al mirar la tercera, tampoco. Seis actuaciones
    seguidas daban "llevan 0" las seis veces.

    Lo que hay que preguntarse no es "cuantas vienen despues", sino "existe
    algun periodo de 45 dias, que incluya a esta, con cinco dentro". Por eso se
    prueban como arranque todas las fechas vecinas.
    """
    todas = sorted(set(fechas) | {incluye})
    mejor = 0
    for arranque in todas:
        fin = arranque + timedelta(days=DIAS_VENTANA)
        if not (arranque <= incluye < fin):
            continue          # esa ventana no contiene la actuacion en cuestion
        mejor = max(mejor, sum(1 for f in todas if arranque <= f < fin))
    return mejor


async def cuantas_hay(db: AsyncSession, *, show_id: int, company_id: int | None,
                      desde: datetime, excluir_id: int | None = None) -> int:
    """Cuantas actuaciones acompañan a esta dentro de un mismo periodo de 45
    dias, SIN contar la propia. Es lo que se enseña como "llevas N"."""
    vecinas = await fechas_vecinas(db, show_id=show_id, company_id=company_id,
                                   cerca_de=desde, excluir_id=excluir_id)
    if not vecinas:
        return 0
    return max(0, _mejor_ventana(vecinas, desde) - 1)


async def aplica(db: AsyncSession, *, show, company_id: int | None,
                 fecha: datetime, incluyendo_esta: bool = True) -> bool:
    """¿Esta actuacion entra ya en tarifa de volumen?"""
    if precio_recurrente(show) is None:
        return False
    n = await cuantas_hay(db, show_id=show.id, company_id=company_id, desde=fecha)
    return (n + (1 if incluyendo_esta else 0)) >= MINIMO


async def estado(db: AsyncSession, *, show, company_id: int | None,
                 desde: datetime) -> dict:
    """Lo que hay que enseñarle al hotel en la ficha.

    Se devuelve SIEMPRE que el show tenga tarifa, aunque falten actuaciones:
    "llevas 3, a la quinta baja a $4,200" vende mas que un descuento que
    aparece solo al final sin avisar.
    """
    tarifa = precio_recurrente(show)
    if tarifa is None:
        return {"tiene": False}
    n = await cuantas_hay(db, show_id=show.id, company_id=company_id, desde=desde)
    return {"tiene": True, "precio": tarifa, "minimo": MINIMO,
            "dias": DIAS_VENTANA, "llevan": n,
            "faltan": max(0, MINIMO - n),
            "activa": n >= MINIMO}


async def recalcular_tras_cancelar(db: AsyncSession, cancelada) -> int:
    """Si una cancelacion deja al hotel por debajo de cinco, devuelve las que
    quedan a su precio normal. Devuelve cuantas se cambiaron.

    SOLO toca actuaciones FUTURAS y SIN FACTURAR. Una que ya se toco y ya se
    timbro no se reprecia: un CFDI no se corrige, se cancela y se emite otro, y
    eso ante el SAT es un tramite de verdad. David lo dio por bueno asi.
    """
    from sqlalchemy.orm import selectinload

    from app.models.show import Show
    from app.services import pricing

    if not cancelada.show_id or not cancelada.company_id:
        return 0
    show = (await db.execute(
        select(Show).options(selectinload(Show.seasonal_rates))
        .where(Show.id == cancelada.show_id))).scalar_one_or_none()
    if show is None or precio_recurrente(show) is None:
        return 0

    ahora = datetime.now()
    ini, fin = ventana(cancelada.starts_at)
    q = (select(Booking)
         .where(Booking.show_id == show.id,
                Booking.company_id == cancelada.company_id,
                Booking.status != BookingStatus.CANCELLED,
                Booking.starts_at >= ini,
                Booking.starts_at < fin))
    vivas = list((await db.execute(q)).scalars().all())
    if len(vivas) >= MINIMO:
        return 0   # siguen siendo cinco o mas: la tarifa se mantiene

    tarifa = precio_recurrente(show)
    cambiadas = 0
    for b in vivas:
        # Ya paso: no se toca. Ya facturada: menos todavia.
        if b.starts_at <= ahora:
            continue
        if getattr(b, "cfdi_id", None) or getattr(b, "invoice_paid", False):
            continue
        if b.agreed_price is None or abs(float(b.agreed_price) - tarifa) > 0.01:
            continue   # no estaba a tarifa de volumen
        b.agreed_price = pricing.effective_price(show, b.starts_at)["price"]
        cambiadas += 1
    return cambiadas
