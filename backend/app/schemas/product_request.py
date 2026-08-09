"""Schemas for the requests board (solicitudes + propuestas)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import ProposalStatus, RequestStatus


# --- Solicitud (request) --------------------------------------------------

class ProductRequestBase(BaseModel):
    title: str
    description: str | None = None
    category: str | None = None
    subcategory: str | None = None
    event_date: datetime | None = None
    city: str | None = None
    region: str | None = None
    budget_min: float | None = None
    budget_max: float | None = None
    currency: str = "MXN"
    venue_photo_url: str | None = None   # foto principal del área/venue
    images: list[str] = Field(default=[], max_length=3)   # hasta 3 fotos del espacio

    # Las solicitudes anteriores a la galería tienen images NULL en la base.
    @field_validator("images", mode="before")
    @classmethod
    def _images_never_none(cls, v):
        return v or []

    @model_validator(mode="after")
    def _check_budget(self):
        if (self.budget_min is not None and self.budget_max is not None
                and self.budget_max < self.budget_min):
            raise ValueError("budget_max must be >= budget_min")
        # La foto principal siempre encabeza la galería; si sólo hay una de las
        # dos, se completa la otra para que la tarjeta tenga siempre imagen.
        if self.venue_photo_url and self.venue_photo_url not in self.images:
            self.images = [self.venue_photo_url] + list(self.images)
        elif self.images and not self.venue_photo_url:
            self.venue_photo_url = self.images[0]
        self.images = list(self.images)[:3]
        return self


class ProductRequestCreate(ProductRequestBase):
    company_id: int | None = None   # el hotel que solicita
    booker_id: int | None = None    # quien lo publica


class ProductRequestUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = None
    description: str | None = None
    category: str | None = None
    subcategory: str | None = None
    event_date: datetime | None = None
    city: str | None = None
    region: str | None = None
    budget_min: float | None = None
    budget_max: float | None = None
    currency: str | None = None
    venue_photo_url: str | None = None
    images: list[str] | None = Field(default=None, max_length=3)
    status: RequestStatus | None = None


class ProductRequestOut(ProductRequestBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    company_id: int | None = None
    booker_id: int | None = None
    status: RequestStatus
    created_at: datetime
    # filled by the endpoint
    company_name: str | None = None
    company_logo: str | None = None
    proposals_count: int = 0


# --- Propuesta (proposal) -------------------------------------------------

class ProposalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artist_id: int   # derived from the artist's own session once artist login lands
    message: str | None = None
    proposed_price: float | None = Field(default=None, ge=0)
    currency: str = "MXN"
    images: list[str] = Field(default=[], max_length=3)   # hasta 3 imágenes de referencia


class ProposalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    request_id: int
    artist_id: int | None = None
    message: str | None = None
    proposed_price: float | None = None
    currency: str
    images: list[str] = []
    status: ProposalStatus
    created_at: datetime
    artist_name: str | None = None
    # set when accepting a proposal auto-generates the actuacion
    booking_id: int | None = None
