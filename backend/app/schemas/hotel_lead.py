"""Schemas for hotel pre-registration leads (prospectos)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
