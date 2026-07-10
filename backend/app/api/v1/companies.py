"""Company (contratante) endpoints: admin CRUD."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, require_permission
from app.models.company import Company
from app.schemas.company import CompanyCreate, CompanyOut, CompanyUpdate

router = APIRouter(prefix="/companies", tags=["companies"])


async def _get_company_or_404(db: DbSession, company_id: int) -> Company:
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return company


@router.get(
    "",
    response_model=list[CompanyOut],
    dependencies=[Depends(require_permission("company.manage"))],
)
async def list_companies(db: DbSession):
    res = await db.execute(select(Company).order_by(Company.name))
    return list(res.scalars().all())


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
    company = Company(**payload.model_dump())
    db.add(company)
    await db.commit()
    await db.refresh(company)
    return company


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
    await db.refresh(company)
    return company


@router.delete(
    "/{company_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("company.manage"))],
)
async def delete_company(company_id: int, db: DbSession):
    company = await _get_company_or_404(db, company_id)
    await db.delete(company)
    await db.commit()
