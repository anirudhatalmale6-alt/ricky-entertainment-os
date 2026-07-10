"""Company (contratante) schemas: create / update / read."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, computed_field

from app.models.enums import RISK_COMMISSION, RiskTier


class CompanyBase(BaseModel):
    name: str
    company_type: str = "hotel"
    risk_tier: RiskTier = RiskTier.A
    agreed_payment_days: int | None = None
    tax_id: str | None = None
    legal_name: str | None = None
    city: str | None = None
    region: str | None = None
    country: str = "Mexico"
    contact_email: str | None = None
    contact_phone: str | None = None


class CompanyCreate(CompanyBase):
    pass


class CompanyUpdate(BaseModel):
    """All fields optional - only provided ones are changed."""
    name: str | None = None
    company_type: str | None = None
    risk_tier: RiskTier | None = None
    agreed_payment_days: int | None = None
    tax_id: str | None = None
    legal_name: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None


class CompanyOut(CompanyBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime

    @computed_field
    @property
    def commission_pct(self) -> float:
        """Commission charged to this company for its current risk tier."""
        return round(RISK_COMMISSION[self.risk_tier] * 100, 2)
