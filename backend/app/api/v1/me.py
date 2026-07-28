"""Self-service endpoints: what the logged-in artist can do to their OWN profile.

The catalogue endpoints in artists.py / shows.py are gated behind
`artist.manage` (an admin/agency permission). An artist managing *their own*
profile shouldn't need that: identity comes from the session (scope.artist_id),
and every write is confined to the profile that belongs to the caller. This is
what powers the "Mi Perfil" screen where a musician edits their tarifas,
descripciones and gestiona sus publicaciones (shows).
"""
import uuid
from datetime import date as date_cls

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete, select, update
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentScope, DbSession
from app.core.config import settings
from app.core.storage import ensure_upload_dir
from app.models.artist import Artist
from app.models.artist_client_rate import ArtistClientRate
from app.models.blocked_date import ArtistBlockedDate
from app.models.booking import Booking
from app.models.company import Company
from app.models.property_group import PropertyGroup
from app.models.contract import (
    ARTIST_CONTRACT_SLUG,
    ContractAcceptance,
    ContractTemplate,
)
from app.models.notification import ArtistNotification
from app.models.media import ArtistDocument, ShowImage
from app.models.seasonal_rate import ShowSeasonalRate
from app.models.show import Show
from app.schemas.artist import ArtistOut, ArtistUpdate
from app.schemas.show import ShowCreate, ShowOut, ShowUpdate


class BlockedDateIn(BaseModel):
    date: date_cls
    reason: str | None = None

router = APIRouter(prefix="/me", tags=["me"])

# Images are resized/compressed on the client before upload, so these are small.
_ALLOWED_IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_MAX_IMAGE_BYTES = 6 * 1024 * 1024

_ARTIST_RELS = (
    selectinload(Artist.shows).selectinload(Show.images),
    selectinload(Artist.shows).selectinload(Show.seasonal_rates),
    selectinload(Artist.documents),
)
_SHOW_RELS = (
    selectinload(Show.images),
    selectinload(Show.seasonal_rates),
)

# Fields an artist may NOT flip on themselves - trust/verification is set by the
# platform, never self-granted.
_PROTECTED = {"is_verified"}


async def _require_artist(scope: CurrentScope) -> int:
    if scope.artist_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta cuenta no tiene un perfil de artista asociado",
        )
    return scope.artist_id


async def _load_artist(db: DbSession, artist_id: int) -> Artist:
    res = await db.execute(
        select(Artist).options(*_ARTIST_RELS).where(Artist.id == artist_id)
    )
    artist = res.scalar_one_or_none()
    if artist is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artist not found")
    return artist


async def _load_show(db: DbSession, show_id: int) -> Show:
    res = await db.execute(select(Show).options(*_SHOW_RELS).where(Show.id == show_id))
    show = res.scalar_one_or_none()
    if show is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Show not found")
    return show


async def _own_show_or_404(db: DbSession, artist_id: int, show_id: int) -> Show:
    show = await _load_show(db, show_id)
    if show.artist_id != artist_id:
        # Don't leak that the show exists under someone else.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Show not found")
    return show


# --- Profile --------------------------------------------------------------

@router.get("/artist", response_model=ArtistOut)
async def get_my_profile(scope: CurrentScope, db: DbSession):
    return await _load_artist(db, await _require_artist(scope))


@router.patch("/artist", response_model=ArtistOut)
async def update_my_profile(payload: ArtistUpdate, scope: CurrentScope, db: DbSession):
    artist_id = await _require_artist(scope)
    artist = await _load_artist(db, artist_id)
    data = payload.model_dump(exclude_unset=True)
    for field in _PROTECTED:
        data.pop(field, None)
    for field, value in data.items():
        setattr(artist, field, value)
    await db.commit()
    return await _load_artist(db, artist_id)


# --- Media upload ---------------------------------------------------------

@router.post("/artist/upload-image")
async def upload_image(scope: CurrentScope, file: UploadFile = File(...)):
    """Store a show photo and return its URL.

    The image is already resized to ~1600px JPEG on the client, so here we only
    validate the type/size and write the bytes. The returned URL includes the
    app's ROOT_PATH so it can be used directly as an <img src> (same origin).
    """
    await _require_artist(scope)
    ext = _ALLOWED_IMAGE_TYPES.get((file.content_type or "").lower())
    if ext is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Formato no admitido. Usa JPG, PNG o WEBP.",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Archivo vacío.")
    if len(data) > _MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="La imagen es muy grande (máximo 6 MB).",
        )
    name = f"{scope.artist_id}_{uuid.uuid4().hex}.{ext}"
    (ensure_upload_dir() / name).write_bytes(data)
    return {"url": f"{settings.ROOT_PATH}/uploads/{name}"}


# --- Legal documents ------------------------------------------------------
# Tipos de documento admitidos (coincide con el registro de artista y /MASTER).
_DOC_TYPES = {
    "identificacion", "comprobante_domicilio", "constancia_sat", "contrato",
    "rider_tecnico", "rider_hospitalidad", "press_kit", "comprobante_bancario", "otro",
}
_ALLOWED_DOC_TYPES = {
    "application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
}
_MAX_DOC_BYTES = 10 * 1024 * 1024


def _doc_out(d: ArtistDocument) -> dict:
    return {"id": d.id, "doc_type": d.doc_type, "url": d.url, "filename": d.filename}


@router.get("/artist/documents")
async def list_my_documents(scope: CurrentScope, db: DbSession):
    """Los documentos legales que el artista ya subió."""
    artist_id = await _require_artist(scope)
    res = await db.execute(
        select(ArtistDocument).where(ArtistDocument.artist_id == artist_id)
    )
    return [_doc_out(d) for d in res.scalars().all()]


@router.post("/artist/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    scope: CurrentScope,
    db: DbSession,
    file: UploadFile = File(...),
    doc_type: str = Form(...),
):
    """Sube (o reemplaza) un documento legal del artista.

    Un solo archivo por tipo: si ya existe uno de ese `doc_type` se reemplaza,
    para que el registro y /MASTER siempre muestren el vigente.
    """
    artist_id = await _require_artist(scope)
    if doc_type not in _DOC_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tipo de documento no válido.")
    ext = _ALLOWED_DOC_TYPES.get((file.content_type or "").lower())
    if ext is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Formato no admitido. Usa PDF, JPG, PNG o WEBP.",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Archivo vacío.")
    if len(data) > _MAX_DOC_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="El documento es muy grande (máximo 10 MB).",
        )
    name = f"doc_{artist_id}_{doc_type}_{uuid.uuid4().hex}.{ext}"
    (ensure_upload_dir() / name).write_bytes(data)
    url = f"{settings.ROOT_PATH}/uploads/{name}"
    filename = (file.filename or f"{doc_type}.{ext}")[:255]

    res = await db.execute(
        select(ArtistDocument).where(
            ArtistDocument.artist_id == artist_id,
            ArtistDocument.doc_type == doc_type,
        )
    )
    doc = res.scalar_one_or_none()
    if doc is None:
        doc = ArtistDocument(artist_id=artist_id, doc_type=doc_type, url=url, filename=filename)
        db.add(doc)
    else:
        doc.url = url
        doc.filename = filename
    await db.commit()
    await db.refresh(doc)
    return _doc_out(doc)


# --- Shows (publicaciones) ------------------------------------------------

@router.get("/artist/shows", response_model=list[ShowOut])
async def list_my_shows(scope: CurrentScope, db: DbSession):
    artist_id = await _require_artist(scope)
    res = await db.execute(
        select(Show).options(*_SHOW_RELS).where(Show.artist_id == artist_id).order_by(Show.show_name)
    )
    return list(res.scalars().unique().all())


@router.post("/artist/shows", response_model=ShowOut, status_code=status.HTTP_201_CREATED)
async def add_my_show(payload: ShowCreate, scope: CurrentScope, db: DbSession):
    artist_id = await _require_artist(scope)
    show = Show(artist_id=artist_id, **payload.model_dump(exclude={"seasonal_rates", "images"}))
    for rate in payload.seasonal_rates:
        show.seasonal_rates.append(ShowSeasonalRate(**rate.model_dump()))
    for img in payload.images:
        show.images.append(ShowImage(**img.model_dump()))
    db.add(show)
    await db.commit()
    return await _load_show(db, show.id)


@router.patch("/artist/shows/{show_id}", response_model=ShowOut)
async def update_my_show(show_id: int, payload: ShowUpdate, scope: CurrentScope, db: DbSession):
    artist_id = await _require_artist(scope)
    show = await _own_show_or_404(db, artist_id, show_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(show, field, value)
    await db.commit()
    return await _load_show(db, show_id)


@router.delete("/artist/shows/{show_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_show(show_id: int, scope: CurrentScope, db: DbSession):
    artist_id = await _require_artist(scope)
    show = await _own_show_or_404(db, artist_id, show_id)
    await db.delete(show)
    await db.commit()


@router.get("/artist/notifications")
async def my_notifications(scope: CurrentScope, db: DbSession):
    """The logged-in artist's bell inbox (avisos de actuaciones)."""
    artist_id = getattr(scope, "artist_id", None)
    if not artist_id:
        return {"unread": 0, "items": []}
    rows = (await db.execute(
        select(ArtistNotification)
        .where(ArtistNotification.artist_id == artist_id)
        .order_by(ArtistNotification.created_at.desc())
        .limit(50)
    )).scalars().all()
    return {
        "unread": sum(1 for r in rows if not r.is_read),
        "items": [{
            "id": r.id,
            "kind": r.kind,
            "title": r.title,
            "body": r.body,
            "starts_at": r.starts_at.isoformat() if r.starts_at else None,
            "is_read": r.is_read,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in rows],
    }


@router.post("/artist/notifications/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_notifications_read(scope: CurrentScope, db: DbSession):
    """Mark all of the artist's notifications as read (opened the bell)."""
    artist_id = getattr(scope, "artist_id", None)
    if artist_id:
        await db.execute(
            update(ArtistNotification)
            .where(
                ArtistNotification.artist_id == artist_id,
                ArtistNotification.is_read.is_(False),
            )
            .values(is_read=True)
        )
        await db.commit()


# --- Contrato (aceptación electrónica = firma) ----------------------------

async def _current_contract(db: DbSession):
    return (await db.execute(
        select(ContractTemplate)
        .where(ContractTemplate.slug == ARTIST_CONTRACT_SLUG)
        .order_by(ContractTemplate.version.desc())
        .limit(1)
    )).scalar_one_or_none()


@router.get("/contract")
async def my_contract(scope: CurrentScope, db: DbSession):
    """Contrato vigente + si el artista ya aceptó ESTA versión.

    El front usa `required` para bloquear el onboarding / mostrar el aviso a los
    artistas que ya existen hasta que acepten la versión actual.
    """
    artist_id = await _require_artist(scope)
    cur = await _current_contract(db)
    if cur is None:
        # Sin contrato publicado todavía: no hay nada que aceptar, no bloquea.
        return {"required": False, "accepted": True, "contract": None}
    accepted = (await db.execute(
        select(ContractAcceptance).where(
            ContractAcceptance.slug == ARTIST_CONTRACT_SLUG,
            ContractAcceptance.version == cur.version,
            ContractAcceptance.user_id == scope.user.id,
        ).limit(1)
    )).scalar_one_or_none()
    return {
        "required": accepted is None,
        "accepted": accepted is not None,
        "accepted_at": accepted.created_at.isoformat() if accepted and accepted.created_at else None,
        "contract": {"version": cur.version, "title": cur.title, "body": cur.body},
    }


@router.post("/contract/accept")
async def accept_contract(request: Request, scope: CurrentScope, db: DbSession):
    """Registra la aceptación de la versión vigente = firma electrónica.

    Guarda nombre, versión, fecha/hora (created_at) e IP. Idempotente: aceptar
    dos veces la misma versión no duplica la constancia.
    """
    artist_id = await _require_artist(scope)
    cur = await _current_contract(db)
    if cur is None:
        raise HTTPException(status_code=404, detail="No hay un contrato vigente por aceptar.")
    existing = (await db.execute(
        select(ContractAcceptance).where(
            ContractAcceptance.slug == ARTIST_CONTRACT_SLUG,
            ContractAcceptance.version == cur.version,
            ContractAcceptance.user_id == scope.user.id,
        ).limit(1)
    )).scalar_one_or_none()
    if existing is None:
        fwd = request.headers.get("x-forwarded-for", "")
        ip = (fwd.split(",")[0].strip() if fwd else "") or (request.client.host if request.client else None)
        db.add(ContractAcceptance(
            slug=ARTIST_CONTRACT_SLUG,
            version=cur.version,
            user_id=scope.user.id,
            artist_id=artist_id,
            signer_name=scope.user.full_name,
            ip=ip,
        ))
        await db.commit()
    return {"accepted": True, "version": cur.version}


# --- Availability blocks (vacaciones / enfermedad) ------------------------

@router.get("/blocked-dates")
async def list_blocked_dates(scope: CurrentScope, db: DbSession):
    """Days the artist marked as unavailable, as 'YYYY-MM-DD' strings."""
    artist_id = await _require_artist(scope)
    rows = (await db.execute(
        select(ArtistBlockedDate)
        .where(ArtistBlockedDate.artist_id == artist_id)
        .order_by(ArtistBlockedDate.blocked_on)
    )).scalars().all()
    return [{"date": r.blocked_on.isoformat(), "reason": r.reason} for r in rows]


@router.post("/blocked-dates", status_code=status.HTTP_201_CREATED)
async def block_date(payload: BlockedDateIn, scope: CurrentScope, db: DbSession):
    """Block one day (idempotent: re-blocking just refreshes the reason)."""
    artist_id = await _require_artist(scope)
    existing = (await db.execute(
        select(ArtistBlockedDate).where(
            ArtistBlockedDate.artist_id == artist_id,
            ArtistBlockedDate.blocked_on == payload.date,
        )
    )).scalar_one_or_none()
    if existing:
        existing.reason = payload.reason
    else:
        db.add(ArtistBlockedDate(artist_id=artist_id, blocked_on=payload.date, reason=payload.reason))
    await db.commit()
    return {"date": payload.date.isoformat(), "reason": payload.reason}


@router.delete("/blocked-dates/{day}", status_code=status.HTTP_204_NO_CONTENT)
async def unblock_date(day: date_cls, scope: CurrentScope, db: DbSession):
    """Remove a block so the day is bookable again."""
    artist_id = await _require_artist(scope)
    await db.execute(
        sa_delete(ArtistBlockedDate).where(
            ArtistBlockedDate.artist_id == artist_id,
            ArtistBlockedDate.blocked_on == day,
        )
    )
    await db.commit()


# --- Tarifas especiales por cliente (descuento del músico a un hotel/cadena) ---

class ClientRateIn(BaseModel):
    company_id: int | None = None
    group_id: int | None = None
    special_price: float | None = None
    discount_pct: float | None = None


def _rate_out(r: ArtistClientRate, company_name=None, group_name=None) -> dict:
    return {
        "id": r.id,
        "company_id": r.company_id,
        "group_id": r.group_id,
        "company_name": company_name,
        "group_name": group_name,
        "special_price": float(r.special_price) if r.special_price is not None else None,
        "discount_pct": float(r.discount_pct) if r.discount_pct is not None else None,
    }


@router.get("/artist/clients")
async def my_clients(scope: CurrentScope, db: DbSession):
    """Hoteles (y cadenas) con los que el artista ha trabajado — para elegir a
    quién ponerle una tarifa especial."""
    artist_id = await _require_artist(scope)
    cids = (await db.execute(
        select(Booking.company_id).where(
            Booking.artist_id == artist_id, Booking.company_id.isnot(None)
        ).distinct()
    )).scalars().all()
    companies = []
    groups = {}
    if cids:
        rows = (await db.execute(
            select(Company.id, Company.name, Company.group_id).where(Company.id.in_(cids))
        )).all()
        for cid, name, gid in rows:
            companies.append({"id": cid, "name": name, "group_id": gid})
            if gid is not None:
                groups[gid] = None
    if groups:
        grows = (await db.execute(
            select(PropertyGroup.id, PropertyGroup.name).where(PropertyGroup.id.in_(groups.keys()))
        )).all()
        groups = {gid: name for gid, name in grows}
    return {
        "companies": companies,
        "groups": [{"id": gid, "name": name} for gid, name in groups.items()],
    }


@router.get("/artist/client-rates")
async def list_client_rates(scope: CurrentScope, db: DbSession):
    artist_id = await _require_artist(scope)
    rates = (await db.execute(
        select(ArtistClientRate).where(ArtistClientRate.artist_id == artist_id)
    )).scalars().all()
    cids = {r.company_id for r in rates if r.company_id}
    gids = {r.group_id for r in rates if r.group_id}
    cnames = {cid: nm for cid, nm in (await db.execute(
        select(Company.id, Company.name).where(Company.id.in_(cids)))).all()} if cids else {}
    gnames = {gid: nm for gid, nm in (await db.execute(
        select(PropertyGroup.id, PropertyGroup.name).where(PropertyGroup.id.in_(gids)))).all()} if gids else {}
    return [_rate_out(r, cnames.get(r.company_id), gnames.get(r.group_id)) for r in rates]


@router.post("/artist/client-rates", status_code=status.HTTP_201_CREATED)
async def add_client_rate(payload: ClientRateIn, scope: CurrentScope, db: DbSession):
    artist_id = await _require_artist(scope)
    if not payload.company_id and not payload.group_id:
        raise HTTPException(status_code=400, detail="Elige un hotel o una cadena.")
    if payload.company_id and payload.group_id:
        raise HTTPException(status_code=400, detail="Elige un hotel O una cadena, no ambos.")
    if payload.special_price is None and payload.discount_pct is None:
        raise HTTPException(status_code=400, detail="Indica un precio especial o un % de descuento.")
    if payload.discount_pct is not None and not (0 < payload.discount_pct <= 100):
        raise HTTPException(status_code=400, detail="El descuento debe estar entre 1 y 100%.")
    # Reemplaza cualquier tarifa previa para el mismo cliente.
    await db.execute(sa_delete(ArtistClientRate).where(
        ArtistClientRate.artist_id == artist_id,
        ArtistClientRate.company_id == payload.company_id,
        ArtistClientRate.group_id == payload.group_id,
    ))
    rate = ArtistClientRate(
        artist_id=artist_id, company_id=payload.company_id, group_id=payload.group_id,
        special_price=payload.special_price, discount_pct=payload.discount_pct,
    )
    db.add(rate)
    await db.commit()
    await db.refresh(rate)
    return _rate_out(rate)


@router.delete("/artist/client-rates/{rate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client_rate(rate_id: int, scope: CurrentScope, db: DbSession):
    artist_id = await _require_artist(scope)
    await db.execute(sa_delete(ArtistClientRate).where(
        ArtistClientRate.id == rate_id, ArtistClientRate.artist_id == artist_id))
    await db.commit()
