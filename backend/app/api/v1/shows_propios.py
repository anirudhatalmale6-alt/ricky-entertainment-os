"""Invitaciones a un show y shows propios de cada hotel (David, 10/11).

Ver models/show_propio para el porqué. Aquí:
  - el hotel crea la invitación a UN show y ve las suyas;
  - el hotel marca el show propio de los proveedores que invitó ANTES de esto;
  - la página pública de la invitación (nombre del hotel y del show);
  - un proveedor que ya existe asigna uno de sus shows a la invitación;
  - MASTER ve todos los shows propios.
El registro de un proveedor nuevo con invitación está en auth.register_artist,
y el show propio se crea al dar de alta su primer show (me.create_my_show).
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentScope, CurrentUser, DbSession, ensure_company_access
from app.core.config import settings
from app.models.artist import Artist
from app.models.company import Company
from app.models.show import Show
from app.models.show_propio import InvitacionShow, ShowPropio
from app.services import pase as pase_svc
from app.services import shows_propios as sp_svc

router = APIRouter(tags=["shows-propios"])


def _ahora() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def url_invitacion(token: str) -> str:
    return f"{settings.public_root.rstrip('/')}/?invshow={token}"


class InvitacionIn(BaseModel):
    show_nombre: str = Field(min_length=2, max_length=160)
    contacto: str | None = Field(default=None, max_length=160)


class MarcarIn(BaseModel):
    show_id: int


async def _show_out(db, sp: ShowPropio) -> dict:
    show = await db.get(Show, sp.show_id)
    artista = await db.get(Artist, sp.artist_id) if sp.artist_id else None
    return {
        "id": sp.id, "company_id": sp.company_id, "show_id": sp.show_id,
        "show_name": show.show_name if show else None,
        "artist_id": sp.artist_id, "artist_name": artista.stage_name if artista else None,
        "artist_codigo": getattr(artista, "codigo", None) if artista else None,
        "origen": sp.origen, "created_at": sp.created_at,
    }


# --- Lado del hotel ----------------------------------------------------------

@router.post("/companies/{company_id}/invitaciones-show", status_code=status.HTTP_201_CREATED)
async def crear_invitacion(company_id: int, payload: InvitacionIn, user: CurrentUser, db: DbSession):
    await ensure_company_access(user, company_id, db)
    if await db.get(Company, company_id) is None:
        raise HTTPException(status_code=404, detail="Hotel no encontrado")
    inv = InvitacionShow(token=pase_svc.nuevo_token(), company_id=company_id,
                         show_nombre=payload.show_nombre.strip(),
                         contacto=(payload.contacto or "").strip() or None,
                         creado_por_user_id=user.id)
    db.add(inv)
    await db.commit()
    return {"id": inv.id, "token": inv.token, "url": url_invitacion(inv.token),
            "show_nombre": inv.show_nombre}


@router.get("/companies/{company_id}/invitaciones-show")
async def listar_invitaciones(company_id: int, user: CurrentUser, db: DbSession):
    await ensure_company_access(user, company_id, db)
    filas = (await db.execute(select(InvitacionShow).where(
        InvitacionShow.company_id == company_id).order_by(InvitacionShow.id.desc()))).scalars().all()
    salida = []
    for i in filas:
        show = await db.get(Show, i.show_id) if i.show_id else None
        art = await db.get(Artist, i.artist_id) if i.artist_id else None
        salida.append({"id": i.id, "show_nombre": i.show_nombre, "contacto": i.contacto,
                       "url": url_invitacion(i.token), "creada": i.created_at,
                       "usada_at": i.usada_at,
                       "show_name": show.show_name if show else None,
                       "artist_name": art.stage_name if art else None})
    return salida


@router.get("/companies/{company_id}/shows-propios")
async def listar_propios(company_id: int, user: CurrentUser, db: DbSession):
    await ensure_company_access(user, company_id, db)
    filas = (await db.execute(select(ShowPropio).where(
        ShowPropio.company_id == company_id).order_by(ShowPropio.id))).scalars().all()
    return [await _show_out(db, sp) for sp in filas]


@router.get("/companies/{company_id}/proveedores-invitados")
async def proveedores_invitados(company_id: int, user: CurrentUser, db: DbSession):
    """Los que este hotel invitó con la liga de antes (sin show). Para que marque
    cuál era su show propio y no se queden fuera de la exención."""
    await ensure_company_access(user, company_id, db)
    propios = {sp.show_id for sp in (await db.execute(select(ShowPropio).where(
        ShowPropio.company_id == company_id))).scalars().all()}
    artistas = (await db.execute(select(Artist).where(
        Artist.invitado_por_company_id == company_id, Artist.is_active.is_(True))
        .order_by(Artist.stage_name))).scalars().all()
    salida = []
    for a in artistas:
        shows = (await db.execute(select(Show).where(
            Show.artist_id == a.id, Show.is_active.is_(True)).order_by(Show.id))).scalars().all()
        salida.append({
            "artist_id": a.id, "artist_name": a.stage_name, "artist_codigo": a.codigo,
            "tiene_propio": any(s.id in propios for s in shows),
            "shows": [{"id": s.id, "show_name": s.show_name, "propio": s.id in propios} for s in shows],
        })
    return salida


@router.post("/companies/{company_id}/shows-propios", status_code=status.HTTP_201_CREATED)
async def marcar_previo(company_id: int, payload: MarcarIn, user: CurrentUser, db: DbSession):
    """Proveedor invitado ANTES de las invitaciones a show: el hotel marca cuál
    es su show propio. Sólo de proveedores que invitó ESTE hotel, y uno por
    proveedor: si no, cualquier hotel se declararía propio el show de otro."""
    await ensure_company_access(user, company_id, db)
    show = await db.get(Show, payload.show_id)
    if show is None:
        raise HTTPException(status_code=404, detail="Show no encontrado")
    artista = await db.get(Artist, show.artist_id) if show.artist_id else None
    if artista is None or artista.invitado_por_company_id != company_id:
        raise HTTPException(status_code=403,
                            detail="Solo puedes marcar shows de proveedores que invitó este hotel.")
    ya = (await db.execute(select(ShowPropio).join(Show, Show.id == ShowPropio.show_id).where(
        ShowPropio.company_id == company_id, Show.artist_id == artista.id))).scalars().first()
    if ya is not None and ya.show_id != show.id:
        raise HTTPException(status_code=409,
                            detail="Ese proveedor ya tiene marcado su show propio con este hotel.")
    sp = await sp_svc.marcar(db, company_id=company_id, show_id=show.id, artist_id=artista.id,
                             origen="previo", user_id=user.id)
    await db.commit()
    return await _show_out(db, sp)


# --- Público y lado del proveedor -------------------------------------------

@router.get("/public/invitacion-show/{token}")
async def invitacion_publica(token: str, db: DbSession):
    inv = (await db.execute(select(InvitacionShow).where(
        InvitacionShow.token == token))).scalar_one_or_none() if token and len(token) >= 16 else None
    if inv is None:
        raise HTTPException(status_code=404, detail="Invitación no válida")
    hotel = await db.get(Company, inv.company_id)
    return {"hotel": hotel.name if hotel else None, "company_id": inv.company_id,
            "show_nombre": inv.show_nombre, "usada": inv.usada_at is not None}


async def usar_invitacion(db, inv: InvitacionShow, show: Show, artista: Artist, origen: str) -> ShowPropio:
    sp = await sp_svc.marcar(db, company_id=inv.company_id, show_id=show.id,
                             artist_id=artista.id, origen=origen, invitacion_id=inv.id)
    inv.usada_at = _ahora()
    inv.show_id = show.id
    inv.artist_id = artista.id
    # Que el hotel le siga viendo aunque elija no ser público (como la liga de antes).
    if artista.invitado_por_company_id is None:
        artista.invitado_por_company_id = inv.company_id
    if artista.invitacion_show_id == inv.id:
        artista.invitacion_show_id = None
    return sp


@router.get("/me/invitacion-show-pendiente")
async def invitacion_pendiente(scope: CurrentScope, db: DbSession):
    """La invitación a un show que el proveedor tiene sin usar: el registro
    empieza por ese show en vez de por el perfil (David, 10/11)."""
    if scope.artist_id is None:
        return {"pendiente": None}
    artista = await db.get(Artist, scope.artist_id)
    if artista is None or not artista.invitacion_show_id:
        return {"pendiente": None}
    inv = await db.get(InvitacionShow, artista.invitacion_show_id)
    if inv is None or inv.usada_at is not None:
        return {"pendiente": None}
    hotel = await db.get(Company, inv.company_id)
    return {"pendiente": {"hotel": hotel.name if hotel else None, "show_nombre": inv.show_nombre}}


@router.post("/me/invitaciones-show/{token}/asignar")
async def asignar_show(token: str, payload: MarcarIn, scope: CurrentScope, db: DbSession):
    """Un proveedor que ya existe acepta la invitación con uno de sus shows."""
    if scope.artist_id is None:
        raise HTTPException(status_code=403, detail="Solo proveedores.")
    inv = (await db.execute(select(InvitacionShow).where(
        InvitacionShow.token == token))).scalar_one_or_none()
    if inv is None:
        raise HTTPException(status_code=404, detail="Invitación no válida")
    if inv.usada_at is not None:
        raise HTTPException(status_code=409, detail="Esta invitación ya se usó.")
    show = await db.get(Show, payload.show_id)
    if show is None or show.artist_id != scope.artist_id:
        raise HTTPException(status_code=404, detail="Show no encontrado")
    artista = await db.get(Artist, scope.artist_id)
    sp = await usar_invitacion(db, inv, show, artista, "asignado")
    await db.commit()
    return await _show_out(db, sp)


@router.post("/me/invitaciones-show/{token}/pendiente")
async def dejar_pendiente(token: str, scope: CurrentScope, db: DbSession):
    """El proveedor que ya existe prefiere crear un show nuevo para esta
    invitación: queda pendiente y su próximo show nuevo la usa."""
    if scope.artist_id is None:
        raise HTTPException(status_code=403, detail="Solo proveedores.")
    inv = (await db.execute(select(InvitacionShow).where(
        InvitacionShow.token == token))).scalar_one_or_none()
    if inv is None or inv.usada_at is not None:
        raise HTTPException(status_code=404, detail="Invitación no válida o ya usada")
    artista = await db.get(Artist, scope.artist_id)
    artista.invitacion_show_id = inv.id
    await db.commit()
    return {"ok": True, "show_nombre": inv.show_nombre}


# --- MASTER --------------------------------------------------------------------

@router.get("/admin/shows-propios")
async def admin_propios(scope: CurrentScope, db: DbSession):
    if not scope.is_admin:
        raise HTTPException(status_code=403, detail="Solo administración.")
    filas = (await db.execute(select(ShowPropio).order_by(ShowPropio.company_id, ShowPropio.id))).scalars().all()
    salida = []
    for sp in filas:
        d = await _show_out(db, sp)
        c = await db.get(Company, sp.company_id)
        d["hotel"] = c.name if c else None
        salida.append(d)
    return salida
