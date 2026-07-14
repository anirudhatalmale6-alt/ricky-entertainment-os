"""Actuacion (booking) schemas: create / update / read + attendance analytics.

An actuacion links a SHOW to a VENUE on a fecha/hora. On read it exposes the
computed attendance metrics David asked for so programming stops being decided
"por popularidad":

  * occupancy_pct  - aforo al iniciar / capacidad de la venue
  * retention_pct  - aforo al terminar / aforo al iniciar  (se quedaron)
  * abandonment_pct- 100 - retention                        (se fueron)
"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, computed_field, model_validator

from app.models.enums import BookingStatus


class BookingBase(BaseModel):
    show_id: int
    venue_id: int
    starts_at: datetime
    ends_at: datetime | None = None
    event_type: str | None = None
    agreed_price: float | None = None
    currency: str = "MXN"
    booker_id: int | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def _check_times(self):
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class BookingCreate(BookingBase):
    """company_id / artist_id / commission_pct are derived server-side from the
    venue and show, so the caller never sets them by hand."""
    pass


class BookingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    event_type: str | None = None
    agreed_price: float | None = None
    currency: str | None = None
    notes: str | None = None


class AttendanceIn(BaseModel):
    """Headcount registered on the night to feed the analytics."""
    model_config = ConfigDict(extra="forbid")
    headcount_start: int | None = None
    headcount_end: int | None = None


class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    show_id: int | None
    venue_id: int | None
    company_id: int | None
    artist_id: int | None
    booker_id: int | None
    starts_at: datetime
    ends_at: datetime | None
    status: BookingStatus
    event_type: str | None
    agreed_price: float | None
    currency: str
    commission_pct: float | None
    headcount_start: int | None
    headcount_end: int | None
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    notes: str | None
    created_at: datetime

    # Venue capacity is carried alongside so occupancy can be computed. Filled by
    # the endpoint (from the loaded venue) - defaults to None if the venue is gone.
    venue_capacity: int | None = None
    venue_name: str | None = None
    show_name: str | None = None
    company_name: str | None = None

    @computed_field
    @property
    def occupancy_pct(self) -> float | None:
        if self.headcount_start is not None and self.venue_capacity:
            return round(self.headcount_start / self.venue_capacity * 100, 1)
        return None

    @computed_field
    @property
    def retention_pct(self) -> float | None:
        if self.headcount_start and self.headcount_end is not None:
            return round(self.headcount_end / self.headcount_start * 100, 1)
        return None

    @computed_field
    @property
    def abandonment_pct(self) -> float | None:
        ret = self.retention_pct
        return round(100 - ret, 1) if ret is not None else None
