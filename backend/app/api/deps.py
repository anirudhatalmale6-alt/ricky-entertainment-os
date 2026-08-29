"""Shared API dependencies: DB session, current user and permission guards."""
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decode_token
from app.db.session import get_db
from app.models.artist import Artist
from app.models.booker import Booker
from app.models.company import Company
from app.models.user import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/login")

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: DbSession,
) -> User:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise credentials_exc
    user_id = payload.get("sub")
    if user_id is None:
        raise credentials_exc

    user = await db.get(User, int(user_id))
    if user is None or not user.is_active:
        raise credentials_exc
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_permission(code: str):
    """Dependency factory guarding an endpoint behind a permission code."""

    async def _guard(user: CurrentUser) -> User:
        if not user.has_permission(code):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {code}",
            )
        return user

    return _guard


async def ensure_company_access(user: User, company_id: int, db: AsyncSession) -> None:
    """Guard access to one property's own resources (venues, budget).

    Admins (``company.manage``) pass for any property. A hotel account passes
    only for its OWN property: either the single property it manages, or any
    property inside the chain it directs. Anyone else gets 403. This lets a
    hotel/chain director self-manage its venues without exposing other clients'
    properties or the fiscal CRUD (which stays admin-only).
    """
    if user.has_permission("company.manage"):
        return
    booker = (
        await db.execute(select(Booker).where(Booker.user_id == user.id))
    ).scalar_one_or_none()
    if booker is not None:
        if booker.company_id is not None and booker.company_id == company_id:
            return
        if booker.group_id is not None:
            company = await db.get(Company, company_id)
            if company is not None and company.group_id == booker.group_id:
                return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="No tienes acceso a esta propiedad.",
    )


async def require_intelligence_access(user: CurrentUser, db: DbSession) -> User:
    """Gate for Market Intelligence / Tendencias / Noticias.

    Abierto para quien tiene ``report.view`` (MASTER y directores de hotel) y,
    ademas, para los artistas marcados como Partner: es el add-on de pago que se
    les cobra, asi que su plan Partner les da acceso a la inteligencia de mercado.
    """
    if user.has_permission("report.view"):
        return user
    artist = (
        await db.execute(select(Artist).where(Artist.user_id == user.id))
    ).scalar_one_or_none()
    if artist and artist.is_partner:
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Market Intelligence requiere permiso de reportes o plan Partner.",
    )


@dataclass
class Scope:
    """Who the caller is and what slice of the marketplace they own.

    Resolved from the linked profile: an artist is scoped to their own artist_id;
    a contratante to their company (a single-property manager) or their whole
    chain (a group director). Admin / finance see everything (is_admin).
    """
    user: User
    role: str | None
    is_admin: bool
    artist_id: int | None
    company_id: int | None
    group_id: int | None
    # La productora ve lo suyo Y lo de sus musicos. Es el mismo reparto que ya
    # existe del lado hotelero: el que dirige una cadena ve todas sus
    # propiedades (group_id), el que lleva una sola ve la suya (company_id).
    #
    # `artist_id` sigue siendo YO y nada mas: es quien firma lo que se escribe
    # (mis fechas bloqueadas, mi ficha). `artist_ids` es lo que se me permite
    # MIRAR. Confundir los dos es como una productora acaba bloqueandose las
    # fechas a si misma al querer bloquear las de un musico.
    artist_ids: tuple[int, ...] = ()
    # Mi productora, si cuelgo de una. Es lo que decide si mi ficha lleva
    # seccion de facturacion: quien cobra es la empresa, no yo.
    parent_id: int | None = None

    @property
    def is_artist(self) -> bool:
        return self.artist_id is not None

    @property
    def is_productora(self) -> bool:
        """Tengo musicos colgando de mi ficha."""
        return len(self.artist_ids) > 1

    def puede_ver_artista(self, artist_id: int | None) -> bool:
        """El admin ve todo; un artista se ve a si mismo y a los suyos."""
        return self.is_admin or (artist_id is not None and artist_id in self.artist_ids)

    @property
    def is_contratante(self) -> bool:
        return self.company_id is not None or self.group_id is not None


async def get_scope(user: CurrentUser, db: DbSession) -> Scope:
    role = user.role.name if user.role else None
    is_admin = user.is_superuser or role in ("admin", "finance")

    artist = (
        await db.execute(select(Artist).where(Artist.user_id == user.id))
    ).scalar_one_or_none()
    booker = (
        await db.execute(select(Booker).where(Booker.user_id == user.id))
    ).scalar_one_or_none()

    # Yo primero y despues los mios. El orden importa poco para filtrar pero
    # mucho al pintar: la productora se ve a si misma arriba de su lista.
    artist_ids: tuple[int, ...] = ()
    if artist is not None:
        hijos = (
            await db.execute(
                select(Artist.id)
                .where(Artist.parent_id == artist.id, Artist.is_active.is_(True))
                .order_by(Artist.stage_name)
            )
        ).scalars().all()
        # Un musico no puede colgar de si mismo: si un dato malo lo dijera, la
        # productora se duplicaria en su propia lista.
        artist_ids = (artist.id, *(h for h in hijos if h != artist.id))

    return Scope(
        user=user,
        role=role,
        is_admin=is_admin,
        artist_id=artist.id if artist else None,
        company_id=booker.company_id if booker else None,
        group_id=booker.group_id if booker else None,
        artist_ids=artist_ids,
        parent_id=artist.parent_id if artist else None,
    )


CurrentScope = Annotated[Scope, Depends(get_scope)]
