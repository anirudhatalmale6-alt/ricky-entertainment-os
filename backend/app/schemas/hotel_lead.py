"""Schemas for hotel pre-registration leads (prospectos)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.fiscal import Rfc


class HotelLeadCreate(BaseModel):
    full_name: str = Field(min_length=2, max_length=255)
    company_name: str = Field(min_length=2, max_length=255)
    position: str | None = Field(default=None, max_length=120)
    email: str = Field(min_length=5, max_length=255)
    phone: str | None = Field(default=None, max_length=40)
    message: str | None = Field(default=None, max_length=2000)


class HotelLeadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    company_name: str
    position: str | None
    email: str
    phone: str | None
    message: str | None
    status: str
    created_at: datetime


class HotelLeadStatusIn(BaseModel):
    status: str = Field(pattern="^(new|contacted|converted|discarded)$")


class HotelLeadConvertIn(BaseModel):
    """Ficha de alta: el admin acepta el prospecto y resguarda todos los datos de
    la propiedad. Todo es opcional excepto que, si no hay password, se genera uno.
    Los campos poblan la empresa (Company) que se crea al convertir."""
    password: str | None = Field(default=None, min_length=6, max_length=128)
    # Datos generales
    company_name: str | None = Field(default=None, max_length=255)   # nombre comercial
    legal_name: str | None = Field(default=None, max_length=255)     # razón social
    tax_id: Rfc = Field(default=None, max_length=20)          # RFC
    fiscal_constancia_url: str | None = Field(default=None, max_length=500)
    # Logo de la propiedad. Se pide ya en el alta manual para que NINGUNA
    # propiedad se quede sin imagen: los logos son los que dan credibilidad en
    # "Experiencia en hoteles" del perfil del proveedor (David 2026-08-14).
    logo_url: str | None = Field(default=None, max_length=500)
    address: str | None = Field(default=None, max_length=255)        # dirección fiscal
    city: str | None = Field(default=None, max_length=120)
    region: str | None = Field(default=None, max_length=120)
    country: str | None = Field(default=None, max_length=80)
    website: str | None = Field(default=None, max_length=255)
    contact_person: str | None = Field(default=None, max_length=255) # nombre completo
    position: str | None = Field(default=None, max_length=120)       # cargo
    contact_phone: str | None = Field(default=None, max_length=40)
    whatsapp: str | None = Field(default=None, max_length=40)
    contact_email: str | None = Field(default=None, max_length=255)
    # Información hotelera / comercial
    company_type: str | None = Field(default=None, max_length=40)    # hotel/resort/centro/eventos
    star_rating: int | None = None
    rooms: int | None = None
    avg_daily_rate: float | None = None
    # Datos financieros
    bank_name: str | None = Field(default=None, max_length=120)
    bank_clabe: str | None = Field(default=None, max_length=20)
    preferred_currency: str | None = Field(default=None, max_length=8)
    agreed_payment_days: int | None = None


class HotelLeadConvertOut(BaseModel):
    """The credentials to hand over to the hotel. The password is shown ONCE."""
    email: str
    password: str
    company_id: int
    company_name: str
