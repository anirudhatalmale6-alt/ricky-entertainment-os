"""Artist endpoints: marketplace catalogue + admin CRUD."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, require_permission
from app.models.artist import Artist
from app.models.seasonal_rate import ArtistSeasonalRate
from app.schemas.artist import ArtistCreate, ArtistOut, ArtistUpdate

router = APIRouter(prefix="/artists", tags=["artists"])


async def _get_artist_or_404(db: DbSession, artist_id: int) -> Artist:
    res = await db.execute(
        select(Artist)
        .options(selectinload(Artist.seasonal_rates))
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
    stmt = select(Artist).options(selectinload(Artist.seasonal_rates)).order_by(Artist.stage_name)
    if category:
        stmt = stmt.where(Artist.category == category)
    if active_only:
        stmt = stmt.where(Artist.is_active.is_(True))
    res = await db.execute(stmt)
    return list(res.scalars().all())


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
    data = payload.model_dump(exclude={"seasonal_rates"})
    artist = Artist(**data)
    for rate in payload.seasonal_rates:
        artist.seasonal_rates.append(ArtistSeasonalRate(**rate.model_dump()))
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
