"""PropertyGroup (chain) schemas + consolidated dashboard for a director."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, computed_field

from app.models.enums import RISK_COMMISSION, RiskTier


class PropertyGroupBase(BaseModel):
    name: str
    legal_name: str | None = None
    tax_id: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None


class PropertyGroupCreate(PropertyGroupBase):
    pass


class PropertyGroupUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = None
    legal_name: str | None = None
    tax_id: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None


class PropertySummary(BaseModel):
    """One property inside a group, as seen in the director's overview."""
    id: int
    name: str
    company_type: str
    city: str | None = None
    risk_tier: RiskTier
    venues_count: int = 0
    total_capacity: int = 0
    bookings_count: int = 0      # actuaciones confirmadas + realizadas
    total_spend: float = 0.0     # gasto en entretenimiento (MXN)

    @computed_field
    @property
    def commission_pct(self) -> float:
        return round(RISK_COMMISSION[self.risk_tier] * 100, 2)


class PropertyGroupOut(PropertyGroupBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime
    property_count: int = 0


class GroupDashboardOut(BaseModel):
    """Consolidated view a chain director sees across all their properties."""
    group_id: int
    group_name: str
    property_count: int
    total_venues: int
    total_capacity: int
    total_bookings: int = 0      # actuaciones de toda la cadena
    total_spend: float = 0.0     # gasto consolidado en entretenimiento (MXN)
    properties: list[PropertySummary] = []
