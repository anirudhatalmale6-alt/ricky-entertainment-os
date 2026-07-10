"""Artist schemas: create / update / read, incl. seasonal rates, media, docs."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, computed_field

from app.models.enums import PAYOUT_COMMISSION, PayoutSpeed


# --- Seasonal rates -------------------------------------------------------

class SeasonalRateCreate(BaseModel):
    label: str
    start_date: date
    end_date: date
    # % over base price (Navidad +300, temporada baja -10). Fully open.
    adjustment_pct: float = 0
    # Optional absolute override - wins over the percentage when provided.
    price: float | None = None


class SeasonalRateOut(SeasonalRateCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


# --- Media / documents ----------------------------------------------------

class ArtistImageCreate(BaseModel):
    url: str
    is_profile: bool = False
    caption: str | None = None


class ArtistImageOut(ArtistImageCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


class ArtistDocumentCreate(BaseModel):
    doc_type: str
    url: str
    filename: str | None = None


class ArtistDocumentOut(ArtistDocumentCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


# --- Artist ---------------------------------------------------------------

class ArtistBase(BaseModel):
    # who they are
    stage_name: str
    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    artist_type: str | None = None
    category: str
    genres: list[str] = []
    bio: str | None = None
    years_experience: str | None = None
    languages_spoken: list[str] = []
    show_languages: list[str] = []

    phone: str | None = None
    email: str | None = None
    website: str | None = None

    # the show + rider
    show_name: str | None = None
    show_description: str | None = None
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
    social_links: dict[str, str] = {}

    # availability
    base_city: str | None = None
    work_radius_km: int | None = None
    states_worked: list[str] = []
    available_to_travel: bool = False
    own_vehicle: bool = False
    valid_passport: bool = False
    usa_visa: bool = False

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
    meals_price: float | None = None         # None = "a acordar"
    per_diem_price: float | None = None       # None = "a acordar"
    special_event_surcharge_pct: float = 0
    payout_speed: PayoutSpeed = PayoutSpeed.MENSUAL

    # marketplace flags
    offers_audition: bool = False
    allow_subcontracting: bool = False
    is_partner: bool = False  # artist registered as provider ("Partner")
    partner_monthly_fee: float | None = None
    calendar_sync: str | None = None  # google / outlook / none

    # registration consents
    accepted_terms: bool = False
    accepted_privacy: bool = False
    authorized_data_use: bool = False

    # fiscal + banking
    rfc: str | None = None
    cfdi_use: str | None = None
    tax_regime: str | None = None
    legal_name: str | None = None
    fiscal_postal_code: str | None = None
    bank_name: str | None = None
    bank_account: str | None = None
    bank_account_holder: str | None = None
    bank_clabe: str | None = None
    preferred_currency: str = "MXN"

    # location
    city: str | None = None
    region: str | None = None
    country: str = "Mexico"
    postal_code: str | None = None


class ArtistCreate(ArtistBase):
    seasonal_rates: list[SeasonalRateCreate] = []
    images: list[ArtistImageCreate] = []
    documents: list[ArtistDocumentCreate] = []


class ArtistUpdate(BaseModel):
    """Partial update - only provided fields are changed."""
    model_config = ConfigDict(extra="forbid")

    stage_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    artist_type: str | None = None
    category: str | None = None
    genres: list[str] | None = None
    bio: str | None = None
    years_experience: str | None = None
    languages_spoken: list[str] | None = None
    show_languages: list[str] | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    show_name: str | None = None
    show_description: str | None = None
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
    social_links: dict[str, str] | None = None
    base_city: str | None = None
    work_radius_km: int | None = None
    states_worked: list[str] | None = None
    available_to_travel: bool | None = None
    own_vehicle: bool | None = None
    valid_passport: bool | None = None
    usa_visa: bool | None = None
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
    payout_speed: PayoutSpeed | None = None
    offers_audition: bool | None = None
    allow_subcontracting: bool | None = None
    is_partner: bool | None = None
    partner_monthly_fee: float | None = None
    calendar_sync: str | None = None
    accepted_terms: bool | None = None
    accepted_privacy: bool | None = None
    authorized_data_use: bool | None = None
    rfc: str | None = None
    cfdi_use: str | None = None
    tax_regime: str | None = None
    legal_name: str | None = None
    fiscal_postal_code: str | None = None
    bank_name: str | None = None
    bank_account: str | None = None
    bank_account_holder: str | None = None
    bank_clabe: str | None = None
    preferred_currency: str | None = None
    city: str | None = None
    region: str | None = None
    country: str | None = None
    postal_code: str | None = None
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
    images: list[ArtistImageOut] = []
    documents: list[ArtistDocumentOut] = []
    created_at: datetime

    @computed_field
    @property
    def payout_commission_pct(self) -> float:
        """Commission the platform charges this artist for their payout speed."""
        return round(PAYOUT_COMMISSION[self.payout_speed] * 100, 2)
