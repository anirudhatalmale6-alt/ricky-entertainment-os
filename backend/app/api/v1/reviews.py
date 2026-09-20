"""Reseñas: sólo las escribe el hotel que contrató, y sólo de lo que ya pasó.

Toda la regla de negocio está en `_actuacion_calificable`. Es lo único que
sostiene la credibilidad del módulo entero: si un día se abre para que alguien
opine sin haber contratado, la calificación deja de valer y con ella el perfil.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api.deps import CurrentScope, DbSession
from app.models.artist import Artist
from app.models.booker import Booker
from app.models.booking import Booking
from app.models.company import Company
from app.models.enums import BookingStatus
from app.models.review import Review
from app.models.show import Show
from app.models.venue import Venue

router = APIRouter(prefix="/reviews", tags=["reviews"])


Banda = Literal["baja", "media", "alta", "muy_alta"]


class ReviewIn(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    comment: str | None = Field(None, max_length=1200)
    # Las dos preguntas de público. Opcionales: quien sólo quiera poner estrellas
    # y comentario debe poder hacerlo — si son obligatorias, nadie califica.
    afluencia: Banda | None = None
    retencion: Banda | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


async def _mis_empresas(db: DbSession, scope: CurrentScope) -> set[int]:
    """Las propiedades que este usuario puede calificar."""
    if scope.company_id:
        return {scope.company_id}
    if scope.group_id is not None:
        ids = (await db.execute(
            select(Company.id).where(Company.group_id == scope.group_id)
        )).scalars().all()
        return set(ids)
    return set()


async def _actuacion_calificable(db: DbSession, booking_id: int, scope: CurrentScope) -> Booking:
    booking = await db.get(Booking, booking_id)
    if booking is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Actuación no encontrada")
    # 1. Tiene que ser de una propiedad tuya. Administración puede corregir.
    if not scope.is_admin:
        if booking.company_id not in await _mis_empresas(db, scope):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Sólo el hotel que contrató esta actuación puede calificarla.",
            )
    # 2. No se califica lo que se canceló: no hubo show que juzgar.
    if booking.status == BookingStatus.CANCELLED:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Esta actuación se canceló, no hay nada que calificar.",
        )
    # 3. Y no se califica por adelantado.
    inicio = _naive(booking.starts_at)
    if inicio and inicio > _now():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Todavía no ocurre. Podrás calificarla cuando termine.",
        )
    return booking


def _out(r: Review, company: Company | None, show: Show | None, cuando: datetime | None) -> dict:
    return {
        "id": r.id,
        "booking_id": r.booking_id,
        "rating": r.rating,
        "comment": r.comment,
        "afluencia": r.afluencia,
        "retencion": r.retencion,
        "author_name": r.author_name,
        "author_position": r.author_position,
        "company_id": r.company_id,
        "company_name": company.name if company else None,
        "company_logo": company.logo_url if company else None,
        "show_id": r.show_id,
        "show_name": show.show_name if show else None,
        "actuacion_fecha": cuando.isoformat() if cuando else None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.post("/bookings/{booking_id}", status_code=status.HTTP_201_CREATED)
async def calificar(booking_id: int, payload: ReviewIn, scope: CurrentScope, db: DbSession):
    """El hotel califica una actuación suya que ya ocurrió. Una por actuación:
    si vuelve a mandar, corrige la que ya había en vez de duplicarla."""
    booking = await _actuacion_calificable(db, booking_id, scope)

    existente = (await db.execute(
        select(Review).where(Review.booking_id == booking_id)
    )).scalar_one_or_none()

    firmante, puesto = None, None
    if scope.user is not None:
        firmante = scope.user.full_name
        booker = (await db.execute(
            select(Booker).where(Booker.user_id == scope.user.id)
        )).scalar_one_or_none()
        if booker:
            puesto = booker.position

    if existente:
        existente.rating = payload.rating
        existente.comment = payload.comment
        existente.afluencia = payload.afluencia
        existente.retencion = payload.retencion
        existente.author_name = firmante or existente.author_name
        existente.author_position = puesto or existente.author_position
        review = existente
    else:
        review = Review(
            booking_id=booking.id,
            artist_id=booking.artist_id,
            show_id=booking.show_id,
            company_id=booking.company_id,
            rating=payload.rating,
            comment=payload.comment,
            afluencia=payload.afluencia,
            retencion=payload.retencion,
            author_name=firmante,
            author_position=puesto,
        )
        db.add(review)
    await db.commit()
    await db.refresh(review)
    # Esta reseña puede mover un ranking: que el siguiente perfil que se abra no
    # sirva el barrido viejo.
    from app.services import distinciones
    distinciones.invalidar()
    company = await db.get(Company, review.company_id) if review.company_id else None
    show = await db.get(Show, review.show_id) if review.show_id else None
    return _out(review, company, show, _naive(booking.starts_at))


@router.get("/artists/{artist_id}")
async def resenas_de_artista(
    artist_id: int, db: DbSession, scope: CurrentScope,
    limit: int = Query(20, ge=1, le=100),
):
    """Lo que dicen los contratantes. Lo ve cualquiera dentro de la plataforma:
    es justo lo que un hotel nuevo necesita leer antes de contratar."""
    rows = list((await db.execute(
        select(Review).where(Review.artist_id == artist_id)
        .order_by(Review.created_at.desc()).limit(limit)
    )).scalars().all())

    empresas: dict[int, Company] = {}
    ids = {r.company_id for r in rows if r.company_id}
    if ids:
        for c in (await db.execute(select(Company).where(Company.id.in_(ids)))).scalars().all():
            empresas[c.id] = c
    shows: dict[int, Show] = {}
    sids = {r.show_id for r in rows if r.show_id}
    if sids:
        for s in (await db.execute(select(Show).where(Show.id.in_(sids)))).scalars().all():
            shows[s.id] = s
    fechas: dict[int, datetime] = {}
    bids = {r.booking_id for r in rows}
    if bids:
        for bid, st in (await db.execute(
            select(Booking.id, Booking.starts_at).where(Booking.id.in_(bids))
        )).all():
            fechas[bid] = _naive(st)

    agg = (await db.execute(
        select(func.avg(Review.rating), func.count(Review.id))
        .where(Review.artist_id == artist_id)
    )).one()
    return {
        "promedio": round(float(agg[0]), 1) if agg[0] is not None else None,
        "total": agg[1],
        "items": [
            _out(r, empresas.get(r.company_id or 0), shows.get(r.show_id or 0),
                 fechas.get(r.booking_id))
            for r in rows
        ],
    }


@router.get("/resumen")
async def resumen_de_periodo(scope: CurrentScope, db: DbSession,
                             year: int | None = None, month: int | None = None):
    """El NIVEL de lo que contrataste en el periodo, más el detalle de reseñas.

    David, 20/09: "el promedio de los artistas que se han contratado, si
    contratas puros de 5, te da promedio de 5, como un score del nivel de
    actuaciones que has contratado".

    O sea que NO es el promedio de las reseñas escritas este mes — eso era lo
    que había antes y en septiembre lo sostenían dos reseñas. Es el promedio de
    la calificación ACUMULADA de cada artista que contrataste, contando una vez
    por actuación: si contratas tres veces al mismo 5 estrellas, el mes pesa
    tres veces hacia el 5. Así el número existe desde el primer mes, porque el
    artista ya trae su historial aunque nadie haya calificado todavía.

    Las actuaciones de artistas que aún no tienen ninguna reseña quedan FUERA
    del promedio, no cuentan como cero: un artista nuevo no es un mal artista.
    Por eso vuelve también `con_nivel` / `actuaciones`, para poder decir sobre
    cuántas está calculado.
    """
    empresas = await _mis_empresas(db, scope)
    vacio = {"promedio": None, "con_nivel": 0, "actuaciones": 0,
             "n": 0, "prom_resenas": None, "sin_calificar": 0, "distribucion": {}}
    if not empresas and not scope.is_admin:
        return vacio

    ini = fin = None
    if year and month:
        ini = datetime(year, month, 1)
        fin = datetime(year + (month == 12), (month % 12) + 1, 1)

    # 1) las actuaciones del periodo y de quién son
    qb = select(Booking.artist_id).where(Booking.status != BookingStatus.CANCELLED)
    if empresas:
        qb = qb.where(Booking.company_id.in_(empresas))
    if ini:
        qb = qb.where(Booking.starts_at >= ini, Booking.starts_at < fin)
    artistas_contratados = [a for a in (await db.execute(qb)).scalars().all() if a]

    # 2) la calificación acumulada de cada artista, de toda su historia
    qn = (select(Review.artist_id, func.avg(Review.rating))
          .where(Review.artist_id.isnot(None)).group_by(Review.artist_id))
    nivel = {aid: float(p) for aid, p in (await db.execute(qn)).all() if p is not None}

    notas = [nivel[a] for a in artistas_contratados if a in nivel]
    promedio = round(sum(notas) / len(notas), 1) if notas else None

    # 3) el detalle de reseñas del periodo, para el panel de satisfacción
    async def _reparto(con_fecha: bool) -> dict[int, int]:
        q = (select(Review.rating, func.count(Review.id))
             .select_from(Review).join(Booking, Booking.id == Review.booking_id)
             .group_by(Review.rating))
        if empresas:
            q = q.where(Booking.company_id.in_(empresas))
        if con_fecha and ini:
            q = q.where(Booking.starts_at >= ini, Booking.starts_at < fin)
        return {int(r): int(n) for r, n in (await db.execute(q)).all() if r is not None}

    dist = await _reparto(True)
    alcance = "periodo"
    if not sum(dist.values()) and ini:
        dist = await _reparto(False)
        alcance = "historico"
    total = sum(dist.values())
    prom_res = (round(sum(r * n for r, n in dist.items()) / total, 1) if total else None)

    qp = (select(func.count(Booking.id)).where(
            Booking.status == BookingStatus.COMPLETED,
            ~Booking.id.in_(select(Review.booking_id))))
    if empresas:
        qp = qp.where(Booking.company_id.in_(empresas))
    if ini:
        qp = qp.where(Booking.starts_at >= ini, Booking.starts_at < fin)
    sin = (await db.execute(qp)).scalar() or 0

    return {"promedio": promedio, "con_nivel": len(notas),
            "actuaciones": len(artistas_contratados),
            "n": total, "prom_resenas": prom_res, "alcance": alcance,
            "sin_calificar": int(sin), "distribucion": dist}


@router.get("/pendientes")
async def pendientes_de_calificar(scope: CurrentScope, db: DbSession):
    """Actuaciones ya realizadas de MIS propiedades que todavía nadie calificó.

    Sin esto el módulo se queda vacío para siempre: nadie entra a la plataforma
    a calificar por iniciativa propia, hay que ponérselo enfrente.
    """
    empresas = await _mis_empresas(db, scope)
    if not empresas and not scope.is_admin:
        return {"items": []}

    q = select(Booking).where(
        Booking.status != BookingStatus.CANCELLED,
        Booking.starts_at < _now(),
    )
    if empresas:
        q = q.where(Booking.company_id.in_(empresas))
    bookings = list((await db.execute(q.order_by(Booking.starts_at.desc()).limit(60))).scalars().all())
    if not bookings:
        return {"items": []}

    ya = set((await db.execute(
        select(Review.booking_id).where(Review.booking_id.in_([b.id for b in bookings]))
    )).scalars().all())
    faltan = [b for b in bookings if b.id not in ya][:20]
    if not faltan:
        return {"items": []}

    artistas: dict[int, Artist] = {}
    aids = {b.artist_id for b in faltan if b.artist_id}
    if aids:
        for a in (await db.execute(select(Artist).where(Artist.id.in_(aids)))).scalars().all():
            artistas[a.id] = a
    shows: dict[int, Show] = {}
    sids = {b.show_id for b in faltan if b.show_id}
    if sids:
        for s in (await db.execute(select(Show).where(Show.id.in_(sids)))).scalars().all():
            shows[s.id] = s
    venues: dict[int, Venue] = {}
    vids = {b.venue_id for b in faltan if b.venue_id}
    if vids:
        for v in (await db.execute(select(Venue).where(Venue.id.in_(vids)))).scalars().all():
            venues[v.id] = v

    return {"items": [
        {
            "booking_id": b.id,
            "artist_id": b.artist_id,
            "artist_name": (artistas.get(b.artist_id or 0).stage_name
                            if artistas.get(b.artist_id or 0) else None),
            "show_name": (shows.get(b.show_id or 0).show_name
                          if shows.get(b.show_id or 0) else None),
            "venue_name": (venues.get(b.venue_id or 0).name
                           if venues.get(b.venue_id or 0) else None),
            "starts_at": _naive(b.starts_at).isoformat() if b.starts_at else None,
        }
        for b in faltan
    ]}
