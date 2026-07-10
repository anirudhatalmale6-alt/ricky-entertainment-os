"""Artist schemas: create / update / read, incl. seasonal rates."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, computed_field

from app.models.enums import PAYOUT_COMMISSION, PayoutSpeed


# --- Seasonal rates -------------------------------------------------------

class SeasonalRateCreate(BaseModel):
    label: str
    start_date: date
    end_date: date
    price: float


class SeasonalRateOut(SeasonalRateCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


# --- Artist ---------------------------------------------------------------

class ArtistBase(BaseModel):
    stage_name: str
    category: str
    bio: str | None = None

    members: int = 1
    duration_minutes: int | None = None
    requirements: str | None = None

    base_price: float | None = None
    special_event_surcharge_pct: float = 0
    payout_speed: PayoutSpeed = PayoutSpeed.MENSUAL

    offers_audition: bool = False
    allow_subcontracting: bool = False
    is_partner: bool = False  # artist registered as provider ("Partner")

    city: str | None = None
    region: str | None = None
    country: str = "Mexico"


class ArtistCreate(ArtistBase):
    seasonal_rates: list[SeasonalRateCreate] = []


class ArtistUpdate(BaseModel):
    """All fields optional - only provided ones are changed."""
    stage_name: str | None = None
    category: str | None = None
    bio: str | None = None
    members: int | None = None
    duration_minutes: int | None = None
    requirements: str | None = None
    base_price: float | None = None
    special_event_surcharge_pct: float | None = None
    payout_speed: PayoutSpeed | None = None
    offers_audition: bool | None = None
    allow_subcontracting: bool | None = None
    is_partner: bool | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    is_verified: bool | None = None
    is_active: bool | None = None


class PriceBenchmarkOut(BaseModel):
    """Market reference so a musician knows if their price is high or low."""
    category: str | None = None
    region: str | None = None
    sample_size: int
    average_price: float | None = None
    min_price: float | None = None
    max_price: float | None = None


class ArtistOut(ArtistBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_verified: bool
    is_active: bool
    rating: float | None = None
    seasonal_rates: list[SeasonalRateOut] = []
    created_at: datetime

    @computed_field
    @property
    def payout_commission_pct(self) -> float:
        """Commission the platform charges this artist for their payout speed."""
        return round(PAYOUT_COMMISSION[self.payout_speed] * 100, 2)
