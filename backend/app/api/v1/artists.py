"""Artist endpoints: marketplace catalogue + admin CRUD."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, require_permission
from app.models.artist import Artist
from app.models.media import ArtistDocument, ArtistImage
from app.models.seasonal_rate import ArtistSeasonalRate
from app.schemas.artist import ArtistCreate, ArtistOut, ArtistUpdate, PriceBenchmarkOut

router = APIRouter(prefix="/artists", tags=["artists"])

_ARTIST_RELS = (
    selectinload(Artist.seasonal_rates),
    selectinload(Artist.images),
    selectinload(Artist.documents),
)


async def _get_artist_or_404(db: DbSession, artist_id: int) -> Artist:
    res = await db.execute(
        select(Artist)
        .options(*_ARTIST_RELS)
        .where(Artist.id == artist_id)
    )
    artist = res.scalar_one_or_none()
    if artist is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artist not found")
    return artist


@router.get("", response_model=list[ArtistOut])
async def list_artists(
    db: DbSession,
    _: CurrentUser,
    category: str | None = Query(None, description="Filter by category"),
    active_only: bool = Query(True, description="Only active artists"),
):
    """Browse the artist catalogue (any authenticated user)."""
    stmt = select(Artist).options(*_ARTIST_RELS).order_by(Artist.stage_name)
    if category:
        stmt = stmt.where(Artist.category == category)
    if active_only:
        stmt = stmt.where(Artist.is_active.is_(True))
    res = await db.execute(stmt)
    return list(res.scalars().all())


@router.get("/price-benchmark", response_model=PriceBenchmarkOut)
async def price_benchmark(
    db: DbSession,
    _: CurrentUser,
    category: str | None = Query(None, description="Category to benchmark against"),
    region: str | None = Query(None, description="Optionally narrow to a region"),
):
    """Average / min / max price of similar acts.

    Gives a musician a reference so they know whether they are charging above
    or below the market for their category (and optionally their region).
    """
    stmt = select(
        func.count(Artist.id),
        func.avg(Artist.base_price),
        func.min(Artist.base_price),
        func.max(Artist.base_price),
    ).where(Artist.is_active.is_(True), Artist.base_price.is_not(None))
    if category:
        stmt = stmt.where(Artist.category == category)
    if region:
        stmt = stmt.where(Artist.region == region)
    count, avg, mn, mx = (await db.execute(stmt)).one()
    return PriceBenchmarkOut(
        category=category,
        region=region,
        sample_size=count or 0,
        average_price=round(float(avg), 2) if avg is not None else None,
        min_price=float(mn) if mn is not None else None,
        max_price=float(mx) if mx is not None else None,
    )


@router.get("/{artist_id}", response_model=ArtistOut)
async def get_artist(artist_id: int, db: DbSession, _: CurrentUser):
    return await _get_artist_or_404(db, artist_id)


@router.post(
    "",
    response_model=ArtistOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("artist.manage"))],
)
async def create_artist(payload: ArtistCreate, db: DbSession):
    data = payload.model_dump(exclude={"seasonal_rates", "images", "documents"})
    artist = Artist(**data)
    for rate in payload.seasonal_rates:
        artist.seasonal_rates.append(ArtistSeasonalRate(**rate.model_dump()))
    for img in payload.images:
        artist.images.append(ArtistImage(**img.model_dump()))
    for doc in payload.documents:
        artist.documents.append(ArtistDocument(**doc.model_dump()))
    db.add(artist)
    await db.commit()
    return await _get_artist_or_404(db, artist.id)


@router.patch(
    "/{artist_id}",
    response_model=ArtistOut,
    dependencies=[Depends(require_permission("artist.manage"))],
)
async def update_artist(artist_id: int, payload: ArtistUpdate, db: DbSession):
    artist = await _get_artist_or_404(db, artist_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(artist, field, value)
    await db.commit()
    return await _get_artist_or_404(db, artist_id)


@router.delete(
    "/{artist_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("artist.manage"))],
)
async def delete_artist(artist_id: int, db: DbSession):
    artist = await _get_artist_or_404(db, artist_id)
    await db.delete(artist)
    await db.commit()
