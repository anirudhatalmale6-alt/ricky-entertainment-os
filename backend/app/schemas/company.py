"""Company (contratante) schemas: create / update / read, with nested venues."""
from __future__ import annotations

from datetime import datetime
from urllib.parse import quote_plus

from pydantic import BaseModel, ConfigDict, computed_field

from app.models.enums import RISK_COMMISSION, RiskTier


# --- Venues ---------------------------------------------------------------

class VenueCreate(BaseModel):
    name: str
    capacity: int | None = None
    ambiance_type: str | None = None
    usual_schedule: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    map_url: str | None = None


class VenueUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    capacity: int | None = None
    ambiance_type: str | None = None
    usual_schedule: str | None = None
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    map_url: str | None = None
    is_active: bool | None = None


class VenueOut(VenueCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    company_id: int
    is_active: bool
    created_at: datetime

    @computed_field
    @property
    def google_maps_url(self) -> str | None:
        """Ready-to-open Google Maps navigation link for the artist."""
        if self.latitude is not None and self.longitude is not None:
            return f"https://www.google.com/maps/search/?api=1&query={self.latitude},{self.longitude}"
        if self.address:
            return f"https://www.google.com/maps/search/?api=1&query={quote_plus(self.address)}"
        return None

    @computed_field
    @property
    def waze_url(self) -> str | None:
        """Ready-to-open Waze navigation link for the artist."""
        if self.latitude is not None and self.longitude is not None:
            return f"https://waze.com/ul?ll={self.latitude},{self.longitude}&navigate=yes"
        if self.address:
            return f"https://waze.com/ul?q={quote_plus(self.address)}"
        return None


# --- Company --------------------------------------------------------------

class CompanyBase(BaseModel):
    name: str
    company_type: str = "hotel"
    logo_url: str | None = None
    group_id: int | None = None   # parent chain/group, if any
    # fiscal
    tax_id: str | None = None
    legal_name: str | None = None
    cfdi_use: str | None = None
    tax_regime: str | None = None
    # contact
    contact_person: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    whatsapp: str | None = None
    website: str | None = None
    social_links: dict[str, str] = {}
    # location
    address: str | None = None
    city: str | None = None
    region: str | None = None
    country: str = "Mexico"
    postal_code: str | None = None
    # commercial
    risk_tier: RiskTier = RiskTier.A
    agreed_payment_days: int | None = None


class CompanyCreate(CompanyBase):
    venues: list[VenueCreate] = []


class CompanyUpdate(BaseModel):
    """All fields optional - only provided ones are changed."""
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    company_type: str | None = None
    logo_url: str | None = None
    group_id: int | None = None
    tax_id: str | None = None
    legal_name: str | None = None
    cfdi_use: str | None = None
    tax_regime: str | None = None
    contact_person: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    whatsapp: str | None = None
    website: str | None = None
    social_links: dict[str, str] | None = None
    address: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    postal_code: str | None = None
    risk_tier: RiskTier | None = None
    agreed_payment_days: int | None = None


class CompanyOut(CompanyBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    venues: list[VenueOut] = []
    created_at: datetime

    @computed_field
    @property
    def commission_pct(self) -> float:
        """Commission charged to this company for its current risk tier."""
        return round(RISK_COMMISSION[self.risk_tier] * 100, 2)
