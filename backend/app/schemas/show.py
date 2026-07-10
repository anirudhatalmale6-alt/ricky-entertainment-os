"""Show schemas: create / update / read, incl. seasonal rates and images."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import ARTIST_CATEGORIES, ARTIST_SUBCATEGORIES, MAX_ARTIST_IMAGES


# --- Seasonal rates -------------------------------------------------------

class SeasonalRateCreate(BaseModel):
    label: str
    start_date: date
    end_date: date
    adjustment_pct: float = 0     # % over base (Navidad +300, baja -10). Open.
    price: float | None = None    # optional absolute override, wins over %


class SeasonalRateOut(SeasonalRateCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


# --- Images ---------------------------------------------------------------

class ShowImageCreate(BaseModel):
    url: str
    is_profile: bool = False
    caption: str | None = None


class ShowImageOut(ShowImageCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


# --- Show -----------------------------------------------------------------

def _validate_category(category: str | None, subcategory: str | None, *, required: bool) -> None:
    if category is None:
        if required:
            raise ValueError("category is required")
        if subcategory is not None and subcategory not in ARTIST_SUBCATEGORIES:
            raise ValueError(f"unknown subcategory '{subcategory}'")
        return
    if category not in ARTIST_CATEGORIES:
        raise ValueError(f"category must be one of {list(ARTIST_CATEGORIES)}")
    if subcategory is not None and subcategory not in ARTIST_CATEGORIES[category]:
        raise ValueError(
            f"subcategory '{subcategory}' is not valid for category '{category}'. "
            f"Options: {ARTIST_CATEGORIES[category]}"
        )


class ShowBase(BaseModel):
    show_name: str
    category: str
    subcategory: str | None = None
    genres: list[str] = []
    description: str | None = None
    show_languages: list[str] = []

    members: int = 1
    duration_minutes: int | None = None
    setup_minutes: int | None = None
    teardown_minutes: int | None = None
    space_required: str | None = None
    power_required: str | None = None
    equipment_included: list[str] = []
    equipment_required: str | None = None
    dressing_room: str | None = None
    requirements: str | None = None

    video_url: str | None = None
    audio_url: str | None = None

    # pricing - one price per event type (all MXN, all optional)
    base_price: float | None = None
    price_hotel: float | None = None
    price_corporate: float | None = None
    price_wedding: float | None = None
    price_private: float | None = None
    price_restaurant: float | None = None
    price_festival: float | None = None
    extra_hour_price: float | None = None
    transport_from_price: float | None = None
    lodging_price: float | None = None       # None = "a acordar"
    meals_price: float | None = None
    per_diem_price: float | None = None
    special_event_surcharge_pct: float = 0

    offers_audition: bool = False

    @model_validator(mode="after")
    def _check_category(self):
        _validate_category(self.category, self.subcategory, required=True)
        return self


class ShowCreate(ShowBase):
    seasonal_rates: list[SeasonalRateCreate] = []
    images: list[ShowImageCreate] = Field(default=[], max_length=MAX_ARTIST_IMAGES)


class ShowUpdate(BaseModel):
    """Partial update - only provided fields are changed."""
    model_config = ConfigDict(extra="forbid")

    show_name: str | None = None
    category: str | None = None
    subcategory: str | None = None
    genres: list[str] | None = None
    description: str | None = None
    show_languages: list[str] | None = None
    members: int | None = None
    duration_minutes: int | None = None
    setup_minutes: int | None = None
    teardown_minutes: int | None = None
    space_required: str | None = None
    power_required: str | None = None
    equipment_included: list[str] | None = None
    equipment_required: str | None = None
    dressing_room: str | None = None
    requirements: str | None = None
    video_url: str | None = None
    audio_url: str | None = None
    base_price: float | None = None
    price_hotel: float | None = None
    price_corporate: float | None = None
    price_wedding: float | None = None
    price_private: float | None = None
    price_restaurant: float | None = None
    price_festival: float | None = None
    extra_hour_price: float | None = None
    transport_from_price: float | None = None
    lodging_price: float | None = None
    meals_price: float | None = None
    per_diem_price: float | None = None
    special_event_surcharge_pct: float | None = None
    offers_audition: bool | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _check_category(self):
        _validate_category(self.category, self.subcategory, required=False)
        return self


class ShowOut(ShowBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    artist_id: int
    is_active: bool
    rating: float | None = None
    seasonal_rates: list[SeasonalRateOut] = []
    images: list[ShowImageOut] = []
    created_at: datetime


class PriceBenchmarkOut(BaseModel):
    """Market reference so a musician knows if their price is high or low."""
    category: str | None = None
    subcategory: str | None = None
    region: str | None = None
    sample_size: int
    average_price: float | None = None
    min_price: float | None = None
    max_price: float | None = None
