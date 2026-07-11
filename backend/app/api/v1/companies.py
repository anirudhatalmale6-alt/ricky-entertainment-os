"""Company (contratante) endpoints: admin CRUD with nested venues."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession, require_permission
from app.models.company import Company
from app.models.property_budget import PropertyBudget
from app.models.venue import Venue
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
    dependencies=[Depends(require_permission("company.manage"))],
)
async def list_venues(company_id: int, db: DbSession):
    res = await db.execute(
        select(Venue).where(Venue.company_id == company_id).order_by(Venue.name)
    )
    return list(res.scalars().all())


@router.post(
    "/{company_id}/venues",
    response_model=VenueOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("company.manage"))],
)
async def add_venue(company_id: int, payload: VenueCreate, db: DbSession):
    await _get_company_or_404(db, company_id)
    venue = Venue(company_id=company_id, **payload.model_dump())
    db.add(venue)
    await db.commit()
    await db.refresh(venue)
    return venue


@router.patch(
    "/venues/{venue_id}",
    response_model=VenueOut,
    dependencies=[Depends(require_permission("company.manage"))],
)
async def update_venue(venue_id: int, payload: VenueUpdate, db: DbSession):
    venue = await _get_venue_or_404(db, venue_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(venue, field, value)
    await db.commit()
    await db.refresh(venue)
    return venue


@router.delete(
    "/venues/{venue_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("company.manage"))],
)
async def delete_venue(venue_id: int, db: DbSession):
    venue = await _get_venue_or_404(db, venue_id)
    await db.delete(venue)
    await db.commit()


# --- Monthly budget ("perfil de presupuesto") ------------------------------

@router.get(
    "/{company_id}/budgets",
    response_model=list[PropertyBudgetOut],
    dependencies=[Depends(require_permission("company.manage"))],
)
async def list_budgets(company_id: int, db: DbSession):
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
    dependencies=[Depends(require_permission("company.manage"))],
)
async def upsert_budget(company_id: int, payload: PropertyBudgetIn, db: DbSession):
    """Load (or overwrite) one month of the property's entertainment budget."""
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
    dependencies=[Depends(require_permission("company.manage"))],
)
async def delete_budget(budget_id: int, db: DbSession):
    row = await db.get(PropertyBudget, budget_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Budget not found")
    await db.delete(row)
    await db.commit()
