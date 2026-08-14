"""Hotel pre-registration (prospectos) endpoints.

POST /leads/hotel is PUBLIC — a hotel leaves its details, no account is created.
The admin sees the prospectos and provisions accounts internally.
"""
import secrets
import string

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import CurrentScope, DbSession
from app.core import security
from app.models.booker import Booker
from app.models.company import Company
from app.models.hotel_lead import HotelLead
from app.models.property_group import PropertyGroup
from app.models.user import Role, User
from app.schemas.hotel_lead import (
    HotelLeadConvertIn,
    HotelLeadConvertOut,
    HotelLeadCreate,
    HotelLeadOut,
    HotelLeadStatusIn,
)

router = APIRouter(prefix="/leads", tags=["leads"])


def _require_admin(scope) -> None:
    if not scope.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el administrador puede ver los prospectos.",
        )


def _gen_password() -> str:
    alpha = string.ascii_letters + string.digits
    return "".join(secrets.choice(alpha) for _ in range(10))


async def _role(db: DbSession, name: str) -> Role | None:
    res = await db.execute(select(Role).where(Role.name == name))
    return res.scalar_one_or_none()


async def _email_taken(db: DbSession, email: str) -> bool:
    res = await db.execute(select(User).where(func.lower(User.email) == email.lower()))
    return res.scalar_one_or_none() is not None


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


@router.post(
    "/hotel/{lead_id}/convert",
    response_model=HotelLeadConvertOut,
    status_code=status.HTTP_201_CREATED,
)
async def convert_hotel_lead(
    lead_id: int, payload: HotelLeadConvertIn, scope: CurrentScope, db: DbSession
):
    """Turn a prospecto into a real hotel account: creates the empresa (Company) +
    the login (User, role booker) + Booker profile, and hands back the credentials
    so the admin can share them. The plaintext password is returned only here."""
    _require_admin(scope)
    lead = await db.get(HotelLead, lead_id)
    if lead is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Prospecto no encontrado")
    if lead.status == "converted":
        raise HTTPException(status.HTTP_409_CONFLICT, "Este prospecto ya tiene una cuenta.")
    if await _email_taken(db, lead.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe una cuenta con ese correo.")

    # `tax_id` ya viene validado y normalizado por el tipo Rfc del esquema: el RFC
    # del hotel es el RECEPTOR de cada factura y, mal escrito, el CFDI no timbra.
    tax_id = payload.tax_id

    name = payload.company_name or lead.company_name
    # Cada hotel/empresa que se da de alta es su propio "grupo" (aunque sea de una
    # sola propiedad): así el usuario entra como DIRECTOR y ve el menú completo
    # (Dashboard, Presupuesto, Facturación, Reportes) igual que la cuenta demo, y
    # las tarifas pactadas a nivel cadena le aplican. Sin grupo, el menú salía
    # "recortado" y el Dashboard quedaba vacío.
    group = PropertyGroup(
        name=name,
        legal_name=payload.legal_name,
        tax_id=tax_id,
        contact_email=(payload.contact_email or lead.email),
        contact_phone=(payload.contact_phone or lead.phone),
    )
    db.add(group)
    await db.flush()

    # Empresa (Company) con toda la ficha de alta que llenó el admin en MASTER.
    company = Company(
        name=name,
        group_id=group.id,
        legal_name=payload.legal_name,
        tax_id=tax_id,
        fiscal_constancia_url=payload.fiscal_constancia_url,
        logo_url=payload.logo_url,
        address=payload.address,
        city=payload.city,
        region=payload.region,
        country=(payload.country or "Mexico"),
        website=payload.website,
        contact_person=(payload.contact_person or lead.full_name),
        contact_email=(payload.contact_email or lead.email),
        contact_phone=(payload.contact_phone or lead.phone),
        whatsapp=payload.whatsapp,
        company_type=(payload.company_type or "hotel"),
        star_rating=payload.star_rating,
        rooms=payload.rooms,
        avg_daily_rate=payload.avg_daily_rate,
        bank_name=payload.bank_name,
        bank_clabe=payload.bank_clabe,
        preferred_currency=(payload.preferred_currency or "MXN"),
        agreed_payment_days=payload.agreed_payment_days,
    )
    db.add(company)
    await db.flush()

    role = await _role(db, "booker")
    plain = payload.password or _gen_password()
    user = User(
        email=lead.email,
        full_name=(payload.contact_person or lead.full_name),
        hashed_password=security.hash_password(plain),
        role_id=role.id if role else None,
    )
    db.add(user)
    await db.flush()

    booker = Booker(
        user_id=user.id,
        company_id=company.id,
        group_id=group.id,
        position=(payload.position or lead.position),
        phone=(payload.contact_phone or lead.phone),
    )
    db.add(booker)
    lead.status = "converted"
    await db.commit()

    return HotelLeadConvertOut(
        email=lead.email,
        password=plain,
        company_id=company.id,
        company_name=company.name,
    )
