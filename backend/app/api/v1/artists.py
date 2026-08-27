"""Artist (profile) endpoints: profile CRUD with nested shows + documents."""
import re
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DbSession, require_permission
from app.core.config import settings
from app.models.artist import Artist
from app.models.enums import ARTIST_CATEGORIES
from app.models.media import ArtistDocument, ShowImage
from app.models.seasonal_rate import ShowSeasonalRate
from app.models.show import Show
from app.schemas.artist import ArtistCreate, ArtistOut, ArtistUpdate, TarjetaIn

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


@router.get("/{artist_id}/trayectoria")
async def artist_trayectoria(artist_id: int, db: DbSession, _: CurrentUser):
    """Lo que la plataforma puede demostrar de este músico.

    Ni un dato lo escribe él: todo sale de sus actuaciones. Es lo que le permite
    a un hotel contratar a alguien que no conoce sin fiarse de un video.
    """
    from app.services import distinciones, trayectoria

    artist = await _get_artist_or_404(db, artist_id)
    datos = await trayectoria.de_artista(db, artist)
    datos["distinciones"] = await distinciones.de_artista(db, artist_id)
    return datos


@router.get("/distinciones/todas")
async def distinciones_del_mercado(db: DbSession, _: CurrentUser):
    """La distinción más fuerte de cada proveedor, para pintarla en las tarjetas
    de búsqueda sin pedir el perfil completo de cada uno."""
    from app.services import distinciones

    ids = list((await db.execute(
        select(Artist.id).where(Artist.is_active.is_(True))
    )).scalars().all())
    fuera = await distinciones.de_varios(db, ids)
    return {str(k): v for k, v in fuera.items() if v}


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


# ---------------------------------------------------------------------------
# TARJETA PUBLICA (perfil compartible fuera de la plataforma)
# ---------------------------------------------------------------------------
# El slug lo genera SIEMPRE el servidor a partir del nombre artistico. No se
# acepta uno del cliente: si se pudiera elegir, el primero en pedirlo se
# quedaria con "dj-nova" y el DJ Nova de verdad tendria que llamarse otra cosa.
_SLUG_MAX = 60


def _slugify(texto: str) -> str:
    # "Mariachi Sol de México" -> "mariachi-sol-de-mexico". Se quitan los
    # acentos a proposito: una URL con % en medio no se puede dictar por
    # telefono ni se ve bien pegada en WhatsApp.
    plano = unicodedata.normalize("NFKD", texto or "")
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    plano = re.sub(r"[^a-zA-Z0-9]+", "-", plano).strip("-").lower()
    return plano[:_SLUG_MAX].strip("-")


async def _slug_libre(db: DbSession, base: str, artist_id: int) -> str:
    """El primer slug que no tenga dueno. Si "dj-nova" ya es de otro, el
    siguiente es "dj-nova-2" y no se le pisa la tarjeta a nadie."""
    if not base:
        base = f"proveedor-{artist_id}"
    candidato, n = base, 1
    while True:
        res = await db.execute(
            select(Artist.id).where(
                Artist.public_slug == candidato, Artist.id != artist_id
            )
        )
        if res.scalar_one_or_none() is None:
            return candidato
        n += 1
        candidato = f"{base[:_SLUG_MAX - 3]}-{n}"


@router.post(
    "/{artist_id}/tarjeta",
    dependencies=[Depends(require_permission("artist.manage"))],
)
async def tarjeta_publica(artist_id: int, payload: TarjetaIn, db: DbSession):
    """Prende o apaga la tarjeta publica de un proveedor.

    Apagarla NO borra el slug: si manana se vuelve a publicar, la liga que ya
    circula por WhatsApp sigue siendo la misma. Borrarlo convertiria cada
    apagon temporal en una liga rota para siempre.
    """
    artist = await _get_artist_or_404(db, artist_id)
    if payload.publicar and not artist.public_slug:
        artist.public_slug = await _slug_libre(db, _slugify(artist.stage_name), artist_id)
    artist.is_public = payload.publicar
    await db.commit()
    await db.refresh(artist)
    return {
        "id": artist.id,
        "is_public": artist.is_public,
        "public_slug": artist.public_slug,
        # La liga completa la arma el servidor: el navegador no sabe si la app
        # vive en la raiz o colgada de /demo.
        "url": (
            f"{settings.public_root}/p/{artist.public_slug}"
            if artist.public_slug else None
        ),
    }
