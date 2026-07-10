"""PropertyGroup - a chain / company group that owns several properties.

Example: a restaurant or hotel chain with 12 properties. A director of the group
gets access to all its properties' dashboards from one place, while each property
(Company) still has its own venues, risk tier and calendar.
"""
from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class PropertyGroup(Base, TimestampMixin):
    __tablename__ = "property_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), index=True)   # "Grupo Hotelero Paraíso"
    legal_name: Mapped[str | None] = mapped_column(String(255))
    tax_id: Mapped[str | None] = mapped_column(String(20))
    contact_email: Mapped[str | None] = mapped_column(String(255))
    contact_phone: Mapped[str | None] = mapped_column(String(40))

    properties: Mapped[list["Company"]] = relationship(  # noqa: F821
        back_populates="group"
    )
    directors: Mapped[list["Booker"]] = relationship(  # noqa: F821
        back_populates="group"
    )
