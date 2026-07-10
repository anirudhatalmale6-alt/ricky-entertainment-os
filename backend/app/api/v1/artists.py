"""Artist (profile) endpoints: profile CRUD with nested shows + documents."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, require_permission
from app.models.artist import Artist
from app.models.enums import ARTIST_CATEGORIES
from app.models.media import ArtistDocument, ShowImage
from app.models.seasonal_rate import ShowSeasonalRate
from app.models.show import Show
from app.schemas.artist import ArtistCreate, ArtistOut, ArtistUpdate

router = APIRouter(prefix="/artists", tags=["artists"])

_ARTIST_RELS = (
    selectinload(Artist.shows).selectinload(Show.images),
    selectinload(Artist.shows).selectinload(Show.seasonal_rates),
    selectinload(Artist.documents),
)


async def _get_artist_or_404(db: DbSession, artist_id: int) -> Artist:
    res = await db.execute(
        select(Artist).options(*_ARTIST_RELS).where(Artist.id == artist_id)
    )
    artist = res.scalar_one_or_none()
    if artist is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artist not found")
    return artist


@router.get("", response_model=list[ArtistOut])
async def list_artists(
    db: DbSession,
    _: CurrentUser,
    active_only: bool = Query(True, description="Only active profiles"),
):
    """Browse artist profiles (any authenticated user)."""
    stmt = select(Artist).options(*_ARTIST_RELS).order_by(Artist.stage_name)
    if active_only:
        stmt = stmt.where(Artist.is_active.is_(True))
    res = await db.execute(stmt)
    return list(res.scalars().unique().all())


@router.get("/taxonomy")
async def category_taxonomy(_: CurrentUser) -> dict[str, list[str]]:
    """Category -> subcategories map that drives the registration dropdowns."""
    return ARTIST_CATEGORIES


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
    artist = Artist(**payload.model_dump(exclude={"shows", "documents"}))
    for show in payload.shows:
        s = Show(**show.model_dump(exclude={"seasonal_rates", "images"}))
        for rate in show.seasonal_rates:
            s.seasonal_rates.append(ShowSeasonalRate(**rate.model_dump()))
        for img in show.images:
            s.images.append(ShowImage(**img.model_dump()))
        artist.shows.append(s)
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
