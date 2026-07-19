"""Artist (profile) schemas: create / update / read, with nested shows + docs."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, computed_field

from app.models.enums import PAYOUT_COMMISSION, PayoutSpeed
from app.schemas.show import ShowCreate, ShowOut


# --- Documents (profile level) --------------------------------------------

class ArtistDocumentCreate(BaseModel):
    doc_type: str
    url: str
    filename: str | None = None


class ArtistDocumentOut(ArtistDocumentCreate):
    model_config = ConfigDict(from_attributes=True)
    id: int


# --- Artist profile -------------------------------------------------------

class ArtistBase(BaseModel):
    # who they are
    stage_name: str
    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    artist_type: str | None = None
    bio: str | None = None
    profile_image_url: str | None = None
    years_experience: str | None = None
    languages_spoken: list[str] = []
    social_links: dict[str, str] = {}

    phone: str | None = None
    email: str | None = None
    website: str | None = None

    # availability
    base_city: str | None = None
    work_radius_km: int | None = None
    states_worked: list[str] = []
    available_to_travel: bool = False
    own_vehicle: bool = False
    valid_passport: bool = False
    usa_visa: bool = False

    # payout preference + marketplace flags
    payout_speed: PayoutSpeed = PayoutSpeed.MENSUAL
    allow_subcontracting: bool = False
    auto_confirm_bookings: bool = False
    is_partner: bool = False
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
    shows: list[ShowCreate] = []
    documents: list[ArtistDocumentCreate] = []


class ArtistUpdate(BaseModel):
    """Partial update - only provided fields are changed."""
    model_config = ConfigDict(extra="forbid")

    stage_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    artist_type: str | None = None
    bio: str | None = None
    profile_image_url: str | None = None
    years_experience: str | None = None
    languages_spoken: list[str] | None = None
    social_links: dict[str, str] | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    base_city: str | None = None
    work_radius_km: int | None = None
    states_worked: list[str] | None = None
    available_to_travel: bool | None = None
    own_vehicle: bool | None = None
    valid_passport: bool | None = None
    usa_visa: bool | None = None
    payout_speed: PayoutSpeed | None = None
    allow_subcontracting: bool | None = None
    auto_confirm_bookings: bool | None = None
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


class ArtistOut(ArtistBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_verified: bool
    is_active: bool
    rating: float | None = None
    shows: list[ShowOut] = []
    documents: list[ArtistDocumentOut] = []
    created_at: datetime

    @computed_field
    @property
    def payout_commission_pct(self) -> float:
        """Commission the platform charges this artist for their payout speed."""
        return round(PAYOUT_COMMISSION[self.payout_speed] * 100, 2)
