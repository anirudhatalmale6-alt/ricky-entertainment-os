"""Quién ve a quién en el catálogo.

Un proveedor puede pedir NO salir para todo el mundo. David lo planteó así: hay
hoteles que van a invitar a sus propios músicos a entrar en SHOWMA, y a ése no
se le puede obligar a quedar expuesto a toda la competencia a cambio de poder
trabajar con quien ya trabajaba.

    catalogo_publico = True   -> lo ve cualquier hotel (el valor por defecto)
    catalogo_publico = False  -> sólo los hoteles con los que YA tiene relación

Lo delicado es qué cuenta como relación. La pregunta exacta de David fue: "si
pone que no está de acuerdo, ¿cómo podría verlo el hotel que lo invitó, y no el
resto?". O sea que la invitación tiene que contar, y contar PRIMERO, porque un
proveedor recién invitado todavía no tiene ninguna actuación: en producción 36
de 53 proveedores no tienen ni una. Sin la invitación escrita, decir que no te
dejaría invisible hasta para quien te trajo, que es lo contrario de lo que se
pretende.

Cuenta como relación, de más fuerte a más débil:

  1. La invitación: ese hotel (o su cadena) lo metió en SHOWMA.
  2. Una actuación con ese hotel, pasada o futura, aunque esté cancelada: si
     alguna vez se contrataron, se conocen.
  3. Una tarifa pactada con ese hotel o con su cadena.
  4. Una conversación abierta entre los dos.

La cadena hereda: si un hotel del grupo lo conoce, el director de la cadena
también lo ve, porque es quien programa para todas sus propiedades.
"""
from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.artist import Artist
from app.models.artist_client_rate import ArtistClientRate
from app.models.booking import Booking
from app.models.company import Company
from app.models.conversation import Conversation


async def _companies_de_la_cadena(db: AsyncSession, group_id: int | None) -> list[int]:
    if group_id is None:
        return []
    return list((await db.execute(
        select(Company.id).where(Company.group_id == group_id)
    )).scalars().all())


async def artistas_visibles(
    db: AsyncSession, artist_ids: list[int], *,
    company_id: int | None, group_id: int | None, es_admin: bool = False,
) -> set[int]:
    """De esos artistas, cuáles puede ver quien pregunta.

    Devuelve el conjunto de ids visibles. Un administrador los ve todos: es
    quien tiene que poder auditar el catálogo entero.
    """
    if es_admin or not artist_ids:
        return set(artist_ids)

    reservados = set((await db.execute(
        select(Artist.id).where(
            Artist.id.in_(artist_ids), Artist.catalogo_publico.is_(False)
        )
    )).scalars().all())
    if not reservados:
        return set(artist_ids)

    # Sin hotel desde el que preguntar no hay relación posible, así que los
    # reservados no se enseñan. Vale para un usuario sin empresa asignada.
    propias = await _companies_de_la_cadena(db, group_id)
    if company_id is not None and company_id not in propias:
        propias.append(company_id)
    if not propias:
        return set(artist_ids) - reservados

    conocidos: set[int] = set()

    # 1. Invitación
    conocidos |= set((await db.execute(
        select(Artist.id).where(
            Artist.id.in_(reservados),
            Artist.invitado_por_company_id.in_(propias),
        )
    )).scalars().all())

    pendientes = reservados - conocidos
    if pendientes:
        # 2. Alguna actuación juntos, en cualquier estado.
        conocidos |= set((await db.execute(
            select(Booking.artist_id).where(
                Booking.artist_id.in_(pendientes),
                Booking.company_id.in_(propias),
            ).distinct()
        )).scalars().all())

    pendientes = reservados - conocidos
    if pendientes:
        # 3. Tarifa pactada con el hotel o con la cadena.
        cond = [ArtistClientRate.company_id.in_(propias)]
        if group_id is not None:
            cond.append(ArtistClientRate.group_id == group_id)
        conocidos |= set((await db.execute(
            select(ArtistClientRate.artist_id).where(
                ArtistClientRate.artist_id.in_(pendientes), or_(*cond)
            ).distinct()
        )).scalars().all())

    pendientes = reservados - conocidos
    if pendientes:
        # 4. Una conversación abierta entre los dos.
        conocidos |= set((await db.execute(
            select(Conversation.artist_id).where(
                Conversation.artist_id.in_(pendientes),
                Conversation.company_id.in_(propias),
            ).distinct()
        )).scalars().all())

    return (set(artist_ids) - reservados) | conocidos


async def puede_verlo(
    db: AsyncSession, artist_id: int, *,
    company_id: int | None, group_id: int | None, es_admin: bool = False,
) -> bool:
    """Lo mismo para un solo proveedor, para las fichas y los perfiles."""
    visibles = await artistas_visibles(
        db, [artist_id], company_id=company_id, group_id=group_id, es_admin=es_admin
    )
    return artist_id in visibles
