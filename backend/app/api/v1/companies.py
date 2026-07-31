"""Company (contratante) endpoints: admin CRUD with nested venues."""
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from pydantic import BaseModel

from app.api.deps import CurrentScope, CurrentUser, DbSession, ensure_company_access, require_permission
from app.core.config import settings
from app.core.storage import ensure_upload_dir
from app.models.booking import Booking
from app.models.company import Company
from app.models.enums import BookingStatus
from app.models.property_budget import PropertyBudget
from app.models.venue import Venue

_ALLOWED_IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_MAX_IMAGE_BYTES = 6 * 1024 * 1024
from app.schemas.company import (
    CompanyCreate,
    CompanyOut,
    CompanyUpdate,
    VenueCreate,
    VenueOut,
    VenueUpdate,
)
from app.schemas.property_budget import PropertyBudgetIn, PropertyBudgetOut

router = APIRouter(prefix="/companies", tags=["companies"])

_COMPANY_RELS = (selectinload(Company.venues),)


async def _get_company_or_404(db: DbSession, company_id: int) -> Company:
    res = await db.execute(
        select(Company).options(*_COMPANY_RELS).where(Company.id == company_id)
    )
    company = res.scalar_one_or_none()
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return company


async def _get_venue_or_404(db: DbSession, venue_id: int) -> Venue:
    venue = await db.get(Venue, venue_id)
    if venue is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Venue not found")
    return venue


@router.get(
    "",
    response_model=list[CompanyOut],
    dependencies=[Depends(require_permission("company.manage"))],
)
async def list_companies(db: DbSession):
    res = await db.execute(select(Company).options(*_COMPANY_RELS).order_by(Company.name))
    return list(res.scalars().unique().all())


@router.get("/mine")
async def my_company(scope: CurrentScope, db: DbSession):
    """La empresa (hotel) de la cuenta actual: su propia empresa, o la primera de
    su cadena si es director. Devuelve lo mínimo para el encabezado del panel,
    incluida su imagen (logo_url). (Debe ir antes de /{company_id}.)"""
    company = None
    if scope.company_id is not None:
        company = await db.get(Company, scope.company_id)
    elif scope.group_id is not None:
        company = (
            await db.execute(
                select(Company).where(Company.group_id == scope.group_id).order_by(Company.id).limit(1)
            )
        ).scalar_one_or_none()
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No hay empresa asociada a tu cuenta")
    return {
        "id": company.id, "name": company.name, "city": company.city,
        "company_type": company.company_type, "logo_url": company.logo_url,
        "group_id": company.group_id,
    }


@router.get(
    "/{company_id}",
    response_model=CompanyOut,
    dependencies=[Depends(require_permission("company.manage"))],
)
async def get_company(company_id: int, db: DbSession):
    return await _get_company_or_404(db, company_id)


@router.post(
    "",
    response_model=CompanyOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("company.manage"))],
)
async def create_company(payload: CompanyCreate, db: DbSession):
    company = Company(**payload.model_dump(exclude={"venues"}))
    for venue in payload.venues:
        company.venues.append(Venue(**venue.model_dump()))
    db.add(company)
    await db.commit()
    return await _get_company_or_404(db, company.id)


@router.patch(
    "/{company_id}",
    response_model=CompanyOut,
    dependencies=[Depends(require_permission("company.manage"))],
)
async def update_company(company_id: int, payload: CompanyUpdate, db: DbSession):
    company = await _get_company_or_404(db, company_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(company, field, value)
    await db.commit()
    return await _get_company_or_404(db, company_id)


@router.delete(
    "/{company_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("company.manage"))],
)
async def delete_company(company_id: int, db: DbSession):
    company = await _get_company_or_404(db, company_id)
    await db.delete(company)
    await db.commit()


# --- Venues ---------------------------------------------------------------

@router.get(
    "/{company_id}/venues",
    response_model=list[VenueOut],
)
async def list_venues(company_id: int, user: CurrentUser, db: DbSession):
    await ensure_company_access(user, company_id, db)
    res = await db.execute(
        select(Venue).where(Venue.company_id == company_id).order_by(Venue.name)
    )
    return list(res.scalars().all())


@router.post(
    "/{company_id}/venues",
    response_model=VenueOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_venue(company_id: int, payload: VenueCreate, user: CurrentUser, db: DbSession):
    await ensure_company_access(user, company_id, db)
    await _get_company_or_404(db, company_id)
    venue = Venue(company_id=company_id, **payload.model_dump())
    db.add(venue)
    await db.commit()
    await db.refresh(venue)
    return venue


@router.patch(
    "/venues/{venue_id}",
    response_model=VenueOut,
)
async def update_venue(venue_id: int, payload: VenueUpdate, user: CurrentUser, db: DbSession):
    venue = await _get_venue_or_404(db, venue_id)
    await ensure_company_access(user, venue.company_id, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(venue, field, value)
    await db.commit()
    await db.refresh(venue)
    return venue


@router.delete(
    "/venues/{venue_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_venue(venue_id: int, user: CurrentUser, db: DbSession):
    venue = await _get_venue_or_404(db, venue_id)
    await ensure_company_access(user, venue.company_id, db)
    await db.delete(venue)
    await db.commit()


# --- Monthly budget ("perfil de presupuesto") ------------------------------

@router.get(
    "/{company_id}/budgets",
    response_model=list[PropertyBudgetOut],
)
async def list_budgets(company_id: int, user: CurrentUser, db: DbSession):
    await ensure_company_access(user, company_id, db)
    await _get_company_or_404(db, company_id)
    res = await db.execute(
        select(PropertyBudget)
        .where(PropertyBudget.company_id == company_id)
        .order_by(PropertyBudget.year.desc(), PropertyBudget.month.desc())
    )
    return list(res.scalars().all())


@router.put(
    "/{company_id}/budgets",
    response_model=PropertyBudgetOut,
)
async def upsert_budget(
    company_id: int, payload: PropertyBudgetIn, user: CurrentUser, db: DbSession
):
    """Load (or overwrite) one month of the property's entertainment budget."""
    await ensure_company_access(user, company_id, db)
    await _get_company_or_404(db, company_id)
    res = await db.execute(
        select(PropertyBudget).where(
            PropertyBudget.company_id == company_id,
            PropertyBudget.year == payload.year,
            PropertyBudget.month == payload.month,
        )
    )
    row = res.scalar_one_or_none()
    if row is None:
        row = PropertyBudget(company_id=company_id, **payload.model_dump())
        db.add(row)
    else:
        for field, value in payload.model_dump().items():
            setattr(row, field, value)
    await db.commit()
    await db.refresh(row)
    return row


@router.delete(
    "/budgets/{budget_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_budget(budget_id: int, user: CurrentUser, db: DbSession):
    row = await db.get(PropertyBudget, budget_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Budget not found")
    await ensure_company_access(user, row.company_id, db)
    await db.delete(row)
    await db.commit()


# --- Facturación: marcar una factura (hotel + mes) como pagada/no pagada -----

class InvoicePaidIn(BaseModel):
    ym: str            # "YYYY-MM" del periodo de la factura
    paid: bool = True


@router.post("/{company_id}/invoice-paid")
async def set_invoice_paid(
    company_id: int, payload: InvoicePaidIn, user: CurrentUser, db: DbSession
):
    """Marca como pagada (o revierte) la factura de un hotel para un mes: pone
    invoice_paid en todas sus actuaciones facturables de ese periodo. La factura
    del hotel se agrupa por hotel + mes, así que este es el marcado a nivel factura."""
    await ensure_company_access(user, company_id, db)
    rows = (
        await db.execute(
            select(Booking).where(
                Booking.company_id == company_id,
                Booking.status.in_((BookingStatus.CONFIRMED, BookingStatus.COMPLETED)),
            )
        )
    ).scalars().all()
    n = 0
    for b in rows:
        dt = b.starts_at
        if dt is not None and f"{dt.year}-{dt.month:02d}" == payload.ym:
            b.invoice_paid = payload.paid
            n += 1
    await db.commit()
    return {"updated": n, "paid": payload.paid}


# --- Imagen del hotel (logo / foto de perfil de la propiedad) ---------------

@router.post("/{company_id}/logo")
async def set_company_logo(
    company_id: int, user: CurrentUser, db: DbSession, file: UploadFile = File(...)
):
    """Sube y fija la imagen del hotel (logo_url). El hotel puede cambiar la suya
    (o el director cualquiera de su cadena); el admin, cualquiera. La imagen ya
    viene redimensionada desde el cliente."""
    await ensure_company_access(user, company_id, db)
    company = await _get_company_or_404(db, company_id)
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
    name = f"company{company_id}_{uuid.uuid4().hex}.{ext}"
    (ensure_upload_dir() / name).write_bytes(data)
    company.logo_url = f"{settings.ROOT_PATH}/uploads/{name}"
    await db.commit()
    return {"logo_url": company.logo_url}
