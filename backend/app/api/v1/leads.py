"""Hotel pre-registration (prospectos) endpoints.

POST /leads/hotel is PUBLIC — a hotel leaves its details, no account is created.
The admin sees the prospectos and provisions accounts internally.
"""
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import CurrentScope, DbSession
from app.models.hotel_lead import HotelLead
from app.schemas.hotel_lead import HotelLeadCreate, HotelLeadOut, HotelLeadStatusIn

router = APIRouter(prefix="/leads", tags=["leads"])


def _require_admin(scope) -> None:
    if not scope.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el administrador puede ver los prospectos.",
        )


@router.post("/hotel", response_model=HotelLeadOut, status_code=status.HTTP_201_CREATED)
async def create_hotel_lead(payload: HotelLeadCreate, db: DbSession):
    """Public pre-registro: capture a hotel's details as a prospecto."""
    lead = HotelLead(**payload.model_dump())
    db.add(lead)
    await db.commit()
    await db.refresh(lead)
    return lead


@router.get("/hotel", response_model=list[HotelLeadOut])
async def list_hotel_leads(scope: CurrentScope, db: DbSession, status_filter: str | None = None):
    _require_admin(scope)
    q = select(HotelLead).order_by(HotelLead.created_at.desc())
    if status_filter:
        q = q.where(HotelLead.status == status_filter)
    res = await db.execute(q)
    return res.scalars().all()


@router.get("/hotel/count")
async def hotel_leads_count(scope: CurrentScope, db: DbSession):
    """Badge count of new (uncontacted) prospectos."""
    _require_admin(scope)
    res = await db.execute(
        select(func.count()).select_from(HotelLead).where(HotelLead.status == "new")
    )
    return {"new": res.scalar_one()}


@router.patch("/hotel/{lead_id}", response_model=HotelLeadOut)
async def update_hotel_lead(
    lead_id: int, payload: HotelLeadStatusIn, scope: CurrentScope, db: DbSession
):
    _require_admin(scope)
    lead = await db.get(HotelLead, lead_id)
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Prospecto no encontrado")
    lead.status = payload.status
    await db.commit()
    await db.refresh(lead)
    return lead
