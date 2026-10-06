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

from sqlalchemy import select
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


def es_oferta(show) -> bool:
    """¿La tarifa de volumen mejora de verdad el precio del hotel?

    En el demo hay un show con precio recurrente 5,000 y precio hotel 5,000.
    Anunciar "cinco o mas y te cuesta 5,000" cuando una sola cuesta 5,000 no es
    una oferta, es ruido, y encima no cambia el precio (solo se aplica si es
    estrictamente menor). Asi que ni se enseña.
    """
    t = precio_recurrente(show)
    base = getattr(show, "price_hotel", None)
    if t is None or base is None:
        return False
    return t < float(base)


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


async def conteos_por_show(db: AsyncSession, *, show_ids: list[int] | set[int],
                           company_id: int | None, cerca_de: datetime) -> dict[int, int]:
    """Lo mismo que `cuantas_hay`, pero para el catalogo entero en UNA consulta.

    El catalogo pinta hasta 40 shows de golpe. Llamar a `cuantas_hay` por cada
    uno son 40 viajes a la base para pintar una pantalla, y el catalogo ya hace
    bastantes. Aqui se traen todas las fechas de una vez y la ventana se calcula
    en memoria, que es donde se calcula igual.
    """
    if not show_ids or not company_id:
        return {}
    q = (select(Booking.show_id, Booking.starts_at)
         .where(Booking.show_id.in_(list(show_ids)),
                Booking.company_id == company_id,
                Booking.status != BookingStatus.CANCELLED,
                Booking.starts_at > cerca_de - timedelta(days=DIAS_VENTANA),
                Booking.starts_at < cerca_de + timedelta(days=DIAS_VENTANA)))
    por_show: dict[int, list[datetime]] = {}
    for sid, cuando in (await db.execute(q)).all():
        por_show.setdefault(sid, []).append(cuando)
    return {sid: max(0, _mejor_ventana(sorted(fechas), cerca_de) - 1)
            for sid, fechas in por_show.items()}


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


async def repreciar_ventana(db: AsyncSession, *, show_id: int | None,
                            company_id: int | None, cerca_de: datetime,
                            hasta: datetime | None = None,
                            precio_anterior: float | None = None) -> int:
    """Repasa las actuaciones de ese show en ese hotel alrededor de esa fecha y
    pone a cada una el precio que le toca HOY. Devuelve cuantas cambiaron.

    Sirve para los dos sentidos, y tiene que ser la misma funcion, porque la
    regla es una sola: cinco actuaciones valen la tarifa de volumen y cuatro no.

      - al CREAR la quinta, las cuatro anteriores bajan a la tarifa.
      - al CANCELAR y quedarse en cuatro, las que queden vuelven a subir.

    Esto salio de una prueba (06/10): se agendaron seis de una en una y solo la
    quinta y la sexta se cobraron a tarifa de volumen. Las cuatro primeras se
    quedaron al precio de lista, porque cada actuacion se calculaba el precio
    cuando nacia y nadie volvia a mirarla. Visto desde el hotel eso es un error:
    contrato cinco, me cobran dos con descuento. Y era asimetrico, porque
    cancelar SI repasaba toda la ventana.

    Dos cosas que NO se tocan:

      - Actuaciones PASADAS o ya FACTURADAS. Un CFDI no se corrige, se cancela y
        se emite otro, y eso ante el SAT es un tramite de verdad.
      - Precios puestos A MANO. Si el importe guardado no coincide con lo que el
        sistema habria calculado, es que alguien lo negocio aparte, y el sistema
        no tiene por que pisarlo. Por eso se compara contra el calculo y no se
        reescribe a ciegas.
    """
    from sqlalchemy.orm import selectinload

    from app.models.show import Show
    # Import local: `tarifa` necesita este modulo, asi que arriba serian
    # importaciones circulares.
    from app.services import tarifa as _tarifa

    if not show_id or not company_id:
        return 0
    show = (await db.execute(
        select(Show).options(selectinload(Show.seasonal_rates))
        .where(Show.id == show_id))).scalar_one_or_none()
    if show is None or precio_recurrente(show) is None:
        return 0

    ahora = datetime.now()
    # Se repasa hacia los DOS lados: una actuacion anterior a la que acaba de
    # nacer tambien forma parte del grupo de cinco. `hasta` existe para la tanda
    # del boton de repetir, que puede abarcar meses: con una sola fecha de
    # referencia quedarian sin repasar las del final de la tanda.
    desde = cerca_de - timedelta(days=DIAS_VENTANA)
    fin = (hasta or cerca_de) + timedelta(days=DIAS_VENTANA)
    vivas = list((await db.execute(
        select(Booking)
        .where(Booking.show_id == show.id,
               Booking.company_id == company_id,
               Booking.status != BookingStatus.CANCELLED,
               Booking.starts_at > desde,
               Booking.starts_at < fin))).scalars().all())

    cambiadas = 0
    for b in vivas:
        if b.starts_at <= ahora:
            continue
        if getattr(b, "cfdi_id", None) or getattr(b, "invoice_paid", False):
            continue
        debido = (await _tarifa.precio_para(
            db, show=show, company_id=company_id, fecha=b.starts_at,
            excluir_booking_id=b.id))["price"]
        if debido is None or b.agreed_price is None:
            continue
        actual = float(b.agreed_price)
        if abs(float(debido) - actual) < 0.01:
            continue
        # Solo se corrige si el importe guardado es uno de los dos que el sistema
        # pudo haber puesto: el calculado de ahora o el de antes del cambio. Si es
        # otro, lo negocio una persona y se respeta.
        candidatos = [float(debido)]
        if precio_anterior is not None:
            candidatos.append(float(precio_anterior))
        tarifa_vol = precio_recurrente(show)
        if tarifa_vol is not None:
            candidatos.append(float(tarifa_vol))
        sin_volumen = (await _tarifa.precio_para(
            db, show=show, company_id=company_id, fecha=b.starts_at,
            excluir_booking_id=b.id, forzar_sin_recurrente=True))["price"]
        if sin_volumen is not None:
            candidatos.append(float(sin_volumen))
        if not any(abs(actual - c) < 0.01 for c in candidatos):
            continue   # precio puesto a mano: no se pisa
        b.agreed_price = debido
        cambiadas += 1
    return cambiadas


async def recalcular_tras_cancelar(db: AsyncSession, cancelada) -> int:
    """Al cancelar: si el hotel baja de cinco, las que queden vuelven a subir."""
    return await repreciar_ventana(
        db, show_id=cancelada.show_id, company_id=cancelada.company_id,
        cerca_de=cancelada.starts_at,
        precio_anterior=float(cancelada.agreed_price) if cancelada.agreed_price is not None else None)


async def recalcular_tras_crear(db: AsyncSession, nueva, hasta: datetime | None = None) -> int:
    """Al crear: si esta es la quinta, las cuatro anteriores bajan a la tarifa.

    `hasta` es la ultima fecha de la tanda cuando se crean varias de golpe.
    """
    return await repreciar_ventana(
        db, show_id=nueva.show_id, company_id=nueva.company_id,
        cerca_de=nueva.starts_at, hasta=hasta)
