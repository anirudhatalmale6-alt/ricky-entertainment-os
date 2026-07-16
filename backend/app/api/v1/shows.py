"""Show endpoints: the marketplace catalogue (the real product) + admin CRUD.

A show belongs to an artist profile (one profile -> many shows). The marketplace
browses and benchmarks SHOWS, since a hotel books a show, not a person.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, require_permission
from app.models.artist import Artist
from app.models.media import ShowImage
from app.models.seasonal_rate import ShowSeasonalRate
from app.models.show import Show
from app.schemas.show import PriceBenchmarkOut, ShowCreate, ShowOut, ShowUpdate

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
    _: CurrentUser,
    category: str | None = Query(None, description="Filter by category"),
    subcategory: str | None = Query(None, description="Filter by subcategory"),
    region: str | None = Query(None, description="Filter by the profile's region"),
    active_only: bool = Query(True, description="Only active shows"),
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
    return list(res.scalars().unique().all())


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
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(show, field, value)
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
