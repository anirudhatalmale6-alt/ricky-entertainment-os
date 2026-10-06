"""El precio que se le cobra a un hotel por una actuación. UN solo sitio.

Por qué existe este archivo: el 30/09 encontré que el catálogo le enseñaba al
hotel un precio y al agendar se guardaba otro. El catálogo aplicaba la tarifa
especial pactada con ese hotel; la creación de la actuación llamaba a
``pricing.effective_price(show, fecha)`` SIN la tarifa, así que cobraba el de
lista. Ocho tarifas vivas, cinco actuaciones cobradas de más (Habana: $3,500
contra una tarifa de $1,200, tres veces).

Eso no era una decisión de negocio mal tomada, era que dos partes del sistema
decían cosas distintas. Y pasó porque cada una calculaba el precio por su
cuenta. La forma de que no vuelva a pasar no es acordarse de pasar el parámetro
en los dos sitios, es que haya un solo sitio donde se decide.

Aquí se resuelve todo lo que hace falta consultar en la base (la tarifa del
cliente, cuántas actuaciones lleva ese hotel para la tarifa de volumen) y se
delega el cálculo en ``pricing.effective_price``, que sigue siendo puro y
testeable sin base de datos.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.artist_client_rate import ArtistClientRate
from app.models.company import Company
from app.services import pricing, recurrente


async def tarifa_cliente(db: AsyncSession, *, artist_id: int | None,
                         company_id: int | None) -> ArtistClientRate | None:
    """La tarifa que ese artista pactó con ese hotel, o con su cadena.

    La del hotel gana sobre la de la cadena: lo más específico manda. Si el
    hotel cuelga de un grupo, la tarifa de cadena también le aplica — es la
    misma regla que usa el catálogo, y tiene que ser la misma, porque si no
    volvemos a tener dos precios.
    """
    if not artist_id or not company_id:
        return None
    group_id = (await db.execute(
        select(Company.group_id).where(Company.id == company_id)
    )).scalar_one_or_none()
    conds = [ArtistClientRate.company_id == company_id]
    if group_id is not None:
        conds.append(ArtistClientRate.group_id == group_id)
    filas = (await db.execute(
        select(ArtistClientRate).where(
            ArtistClientRate.artist_id == artist_id, or_(*conds))
    )).scalars().all()
    if not filas:
        return None
    especificas = [r for r in filas if r.company_id is not None]
    return (especificas or filas)[0]


async def precio_para(db: AsyncSession, *, show, company_id: int | None,
                      fecha: datetime, distancia_km: float | None = None,
                      excluir_booking_id: int | None = None,
                      cuenta_extra: int = 0,
                      forzar_sin_recurrente: bool = False) -> dict:
    """El precio de esa actuación para ese hotel en esa fecha, y de dónde sale.

    Devuelve lo mismo que ``pricing.effective_price``. ``cuenta_extra`` son
    actuaciones que todavía no están en la base pero se van a crear en la misma
    tanda (el botón de repetir): sin eso, crear cinco de golpe no activaría la
    tarifa de volumen hasta la siguiente vez.

    ``forzar_sin_recurrente`` devuelve el precio que tendría SIN la tarifa de
    volumen. Se usa para reconocer un importe que puso el sistema antes de que se
    alcanzaran las cinco, y así no confundirlo con uno negociado a mano.
    """
    rate = await tarifa_cliente(db, artist_id=getattr(show, "artist_id", None),
                                company_id=company_id)
    tarifa_rec = recurrente.precio_recurrente(show)
    activa = False
    if tarifa_rec is not None and company_id and not forzar_sin_recurrente:
        n = await recurrente.cuantas_hay(
            db, show_id=show.id, company_id=company_id, desde=fecha,
            excluir_id=excluir_booking_id)
        activa = (n + 1 + cuenta_extra) >= recurrente.MINIMO
    return pricing.effective_price(
        show, fecha, rate, distance_km=distancia_km,
        recurrent_price=tarifa_rec if activa else None,
    )
