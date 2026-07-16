"""HotelLead - a hotel/venue PRE-REGISTRO (prospecto).

Hotels do NOT self-register with a password. They leave their details, an alert
reaches the admin, and the admin provisions the real account internally and hands
over the user + password (David 2026-07-16).
"""
from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class HotelLead(Base, TimestampMixin):
    __tablename__ = "hotel_leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255))
    company_name: Mapped[str] = mapped_column(String(255))     # hotel / empresa
    position: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), index=True)
    phone: Mapped[str | None] = mapped_column(String(40))
    message: Mapped[str | None] = mapped_column(Text)
    # new -> contacted -> converted / discarded
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
