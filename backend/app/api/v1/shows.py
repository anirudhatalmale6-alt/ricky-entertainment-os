"""Show endpoints: the marketplace catalogue (the real product) + admin CRUD.

A show belongs to an artist profile (one profile -> many shows). The marketplace
browses and benchmarks SHOWS, since a hotel books a show, not a person.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentScope, CurrentUser, DbSession, require_permission
from app.models.artist import Artist
from app.models.artist_client_rate import ArtistClientRate
from app.models.company import Company
from app.models.media import ShowImage
from app.models.seasonal_rate import ShowSeasonalRate
from app.models.show import Show
from app.models.venue import Venue
from app.schemas.show import PriceBenchmarkOut, ShowCreate, ShowOut, ShowUpdate
from app.services import availability, geo, pricing

router = APIRouter(tags=["shows"])

_SHOW_RELS = (
    selectinload(Show.images),
    selectinload(Show.seasonal_rates),
)


async def _get_show_or_404(db: DbSession, show_id: int) -> Show:
    res = await db.execute(
        select(Show).options(*_SHOW_RELS).where(Show.id == show_id)
    )
    show = res.scalar_one_or_none()
    if show is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Show not found")
    return show


@router.get("/shows", response_model=list[ShowOut])
async def list_shows(
    db: DbSession,
    scope: CurrentScope,
    category: str | None = Query(None, description="Filter by category"),
    subcategory: str | None = Query(None, description="Filter by subcategory"),
    region: str | None = Query(None, description="Filter by the profile's region"),
    active_only: bool = Query(True, description="Only active shows"),
    on: datetime | None = Query(
        None, description="Fecha de la actuación: aplica la tarifa de temporada del show"),
    near_company_id: int | None = Query(
        None, description="Hotel de referencia para calcular la distancia; por defecto, el del usuario"),
    near_venue_id: int | None = Query(
        None, description="Venue de referencia (gana sobre near_company_id): se usa el hotel al que pertenece"),
    max_km: float | None = Query(
        None, ge=0, description="Sólo proveedores a esa distancia o menos (los de ubicación desconocida siempre pasan)"),
):
    """Marketplace catalogue of shows."""
    stmt = select(Show).options(*_SHOW_RELS).order_by(Show.show_name)
    if category:
        stmt = stmt.where(Show.category == category)
    if subcategory:
        stmt = stmt.where(Show.subcategory == subcategory)
    if region:
        stmt = stmt.join(Artist, Show.artist_id == Artist.id).where(Artist.region == region)
    if active_only:
        stmt = stmt.where(Show.is_active.is_(True))
    res = await db.execute(stmt)
    shows = list(res.scalars().unique().all())

    # Enriquecer con nombre del artista + una imagen: foto del show (la marcada como
    # perfil, o la primera) y, si el show no tiene fotos, la foto de perfil del artista.
    artist_ids = {s.artist_id for s in shows if s.artist_id}
    names: dict[int, str] = {}
    avatars: dict[int, str | None] = {}
    cities: dict[int, str | None] = {}
    regions: dict[int, str | None] = {}
    partners: dict[int, bool] = {}
    if artist_ids:
        rows = (await db.execute(
            select(Artist.id, Artist.stage_name, Artist.profile_image_url,
                   Artist.base_city, Artist.region, Artist.is_partner)
            .where(Artist.id.in_(artist_ids))
        )).all()
        for aid, nm, av, city, region_, partner in rows:
            names[aid] = nm
            avatars[aid] = av
            cities[aid] = city
            regions[aid] = region_
            partners[aid] = bool(partner)
    # Tarifas especiales: si el hotel/cadena que consulta tiene una tarifa pactada
    # con el artista, el precio efectivo la refleja (sin tocar el precio público).
    scope_company_id = scope.company_id
    scope_group_id = scope.group_id
    # Si consulta un hotel (nivel empresa) pero la tarifa se pactó con la CADENA,
    # igual debe aplicarle: resolvemos el grupo de su empresa para incluir las
    # tarifas de cadena, no solo las específicas del hotel.
    if scope_company_id is not None and scope_group_id is None:
        scope_group_id = (await db.execute(
            select(Company.group_id).where(Company.id == scope_company_id)
        )).scalar_one_or_none()
    rate_by_artist: dict[int, ArtistClientRate] = {}
    if artist_ids and (scope_company_id is not None or scope_group_id is not None):
        conds = []
        if scope_company_id is not None:
            conds.append(ArtistClientRate.company_id == scope_company_id)
        if scope_group_id is not None:
            conds.append(ArtistClientRate.group_id == scope_group_id)
        rrows = (await db.execute(
            select(ArtistClientRate).where(
                ArtistClientRate.artist_id.in_(artist_ids), or_(*conds))
        )).scalars().all()
        for r in rrows:
            # una tarifa por artista; la específica del hotel gana sobre la de cadena
            if r.artist_id not in rate_by_artist or r.company_id is not None:
                rate_by_artist[r.artist_id] = r

    # Disponibilidad del día consultado: días bloqueados por el propio artista
    # (vacaciones/enfermedad) y actuaciones que ya tiene esa fecha.
    day = availability.as_date(on)
    blocked = await availability.blocked_on(db, day) if day else {}
    busy = await availability.busy_on(db, day) if day else {}

    # Distancia al hotel que consulta. El venue manda (es donde ocurre el show),
    # luego el hotel indicado y, si no, el del propio usuario — un administrador
    # no está ligado a ningún hotel, por eso hace falta el venue.
    origin_company_id = near_company_id if near_company_id is not None else scope.company_id
    if near_venue_id is not None:
        v_company = (await db.execute(
            select(Venue.company_id).where(Venue.id == near_venue_id)
        )).scalar_one_or_none()
        if v_company is not None:
            origin_company_id = v_company
    origin: tuple[str | None, str | None] | None = None
    if origin_company_id is not None:
        row = (await db.execute(
            select(Company.city, Company.region).where(Company.id == origin_company_id)
        )).first()
        if row is not None:
            origin = (row[0], row[1])

    for s in shows:
        imgs = list(s.images or [])
        show_img = None
        if imgs:
            profile = next((i for i in imgs if i.is_profile), None)
            show_img = (profile or imgs[0]).url
        s.artist_name = names.get(s.artist_id)
        s.image_url = show_img or avatars.get(s.artist_id)
        s.artist_city = cities.get(s.artist_id)
        s.artist_region = regions.get(s.artist_id)
        s.artist_partner = partners.get(s.artist_id, False)
        # Precio efectivo = base → temporada del show (si la fecha cae dentro) →
        # tarifa especial pactada con ese hotel/cadena.
        info = pricing.effective_price(s, on, rate_by_artist.get(s.artist_id))
        s.effective_price = info["price"]
        s.has_special_rate = info["has_special_rate"]
        s.season_label = info["season_label"]
        s.season_pct = info["season_pct"]
        s.has_season = info["has_season"]
        # Disponibilidad. Un día bloqueado por el artista es definitivo: no se
        # puede contratar. Tener ya otra actuación ese día sólo se avisa — el
        # choque real (con 1 h de margen) se revisa al guardar, con la hora.
        if day:
            if s.artist_id in blocked:
                s.is_available = False
                motivo = blocked[s.artist_id]
                s.unavailable_reason = (
                    f"El artista bloqueó ese día en su calendario ({motivo})" if motivo
                    else "El artista bloqueó ese día en su calendario"
                )
            else:
                s.is_available = True
                if s.artist_id in busy:
                    s.busy_note = f"Ya tiene otra actuación ese día a las {busy[s.artist_id]:%H:%M}"
        # Distancia
        if origin is not None:
            s.distance_km = geo.distance_km(origin[0], origin[1], s.artist_city, s.artist_region)

    if max_km is not None:
        # Los de ubicación desconocida se quedan: no los escondemos por un dato
        # que todavía no han capturado.
        shows = [s for s in shows if s.distance_km is None or s.distance_km <= max_km]
    return shows


@router.get("/shows/price-benchmark", response_model=PriceBenchmarkOut)
async def price_benchmark(
    db: DbSession,
    _: CurrentUser,
    category: str | None = Query(None, description="Category to benchmark against"),
    subcategory: str | None = Query(None, description="Narrow to a subcategory (familia), e.g. DJ vs Orquesta"),
    region: str | None = Query(None, description="Optionally narrow to a region"),
):
    """Average / min / max base price of similar shows, so an artist knows
    whether their price is above or below the market. Narrows by category and,
    when given, by subcategory (familia) - so a DJ compares with DJs, not with
    orquestas - and optionally by region."""
    stmt = select(
        func.count(Show.id),
        func.avg(Show.base_price),
        func.min(Show.base_price),
        func.max(Show.base_price),
    ).where(Show.is_active.is_(True), Show.base_price.is_not(None))
    if category:
        stmt = stmt.where(Show.category == category)
    if subcategory:
        stmt = stmt.where(Show.subcategory == subcategory)
    if region:
        stmt = stmt.join(Artist, Show.artist_id == Artist.id).where(Artist.region == region)
    count, avg, mn, mx = (await db.execute(stmt)).one()
    return PriceBenchmarkOut(
        category=category,
        subcategory=subcategory,
        region=region,
        sample_size=count or 0,
        average_price=round(float(avg), 2) if avg is not None else None,
        min_price=float(mn) if mn is not None else None,
        max_price=float(mx) if mx is not None else None,
    )


@router.get("/shows/novedades")
async def novedades(
    db: DbSession,
    _: CurrentUser,
    days: int = Query(7, ge=1, le=60, description="Antigüedad máxima en días"),
    limit: int = Query(12, ge=1, le=50),
):
    """Recently published shows — 'Novedades'. Powers the hotel dashboard's
    suggestions and the "Novedad" tag on new listings (David: los artistas recién
    registrados aparecen para facilitar que los contraten aunque acaben de empezar)."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(days=days)
    stmt = (
        select(Show)
        .options(*_SHOW_RELS)
        .join(Artist, Show.artist_id == Artist.id)
        .where(Show.is_active.is_(True), Show.created_at >= cutoff)
        .order_by(Show.created_at.desc())
        .limit(limit)
    )
    shows = list((await db.execute(stmt)).scalars().unique().all())
    artist_ids = {s.artist_id for s in shows}
    names: dict[int, str] = {}
    if artist_ids:
        rows = (await db.execute(select(Artist.id, Artist.stage_name).where(Artist.id.in_(artist_ids)))).all()
        names = {aid: nm for aid, nm in rows}

    def _image(s: Show) -> str | None:
        imgs = list(s.images or [])
        if not imgs:
            return None
        profile = next((i for i in imgs if i.is_profile), None)
        return (profile or imgs[0]).url

    out = []
    for s in shows:
        created = s.created_at
        days_ago = (now - created).days if created else None
        out.append({
            "id": s.id,
            "show_name": s.show_name,
            "category": s.category,
            "subcategory": s.subcategory,
            "artist_id": s.artist_id,
            "artist_name": names.get(s.artist_id),
            "base_price": float(s.base_price) if s.base_price is not None else None,
            "price_hotel": float(s.price_hotel) if s.price_hotel is not None else None,
            "image_url": _image(s),
            "created_at": created.isoformat() if created else None,
            "days_ago": days_ago,
        })
    return {"days": days, "count": len(out), "novedades": out}


@router.get("/shows/{show_id}", response_model=ShowOut)
async def get_show(show_id: int, db: DbSession, _: CurrentUser):
    return await _get_show_or_404(db, show_id)


@router.get("/artists/{artist_id}/shows", response_model=list[ShowOut])
async def list_artist_shows(artist_id: int, db: DbSession, _: CurrentUser):
    res = await db.execute(
        select(Show).options(*_SHOW_RELS).where(Show.artist_id == artist_id).order_by(Show.show_name)
    )
    return list(res.scalars().unique().all())


@router.post(
    "/artists/{artist_id}/shows",
    response_model=ShowOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("artist.manage"))],
)
async def add_show(artist_id: int, payload: ShowCreate, db: DbSession):
    """Add another show to an existing profile ("Anadir otro show")."""
    artist = (await db.execute(select(Artist).where(Artist.id == artist_id))).scalar_one_or_none()
    if artist is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artist not found")
    show = Show(artist_id=artist_id, **payload.model_dump(exclude={"seasonal_rates", "images"}))
    for rate in payload.seasonal_rates:
        show.seasonal_rates.append(ShowSeasonalRate(**rate.model_dump()))
    for img in payload.images:
        show.images.append(ShowImage(**img.model_dump()))
    db.add(show)
    await db.commit()
    return await _get_show_or_404(db, show.id)


@router.patch(
    "/shows/{show_id}",
    response_model=ShowOut,
    dependencies=[Depends(require_permission("artist.manage"))],
)
async def update_show(show_id: int, payload: ShowUpdate, db: DbSession):
    show = await _get_show_or_404(db, show_id)
    data = payload.model_dump(exclude_unset=True)
    rates = data.pop("seasonal_rates", None)
    for field, value in data.items():
        setattr(show, field, value)
    if rates is not None:
        show.seasonal_rates.clear()
        for rate in rates:
            show.seasonal_rates.append(ShowSeasonalRate(**rate))
    await db.commit()
    return await _get_show_or_404(db, show_id)


@router.delete(
    "/shows/{show_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("artist.manage"))],
)
async def delete_show(show_id: int, db: DbSession):
    show = await _get_show_or_404(db, show_id)
    await db.delete(show)
    await db.commit()
