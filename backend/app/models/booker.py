"""Booker model - a person who books entertainment on behalf of a company."""
from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Booker(Base, TimestampMixin):
    __tablename__ = "bookers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    # A group director oversees a whole chain: group_id set, company_id may be null.
    # A single-property manager: company_id set, group_id null.
    group_id: Mapped[int | None] = mapped_column(
        ForeignKey("property_groups.id", ondelete="SET NULL"), index=True
    )

    position: Mapped[str | None] = mapped_column(String(120))  # e.g. "Director de actividades"
    phone: Mapped[str | None] = mapped_column(String(40))

    user: Mapped["User"] = relationship(back_populates="booker_profile")  # noqa: F821
    company: Mapped["Company | None"] = relationship(back_populates="bookers")  # noqa: F821
    group: Mapped["PropertyGroup | None"] = relationship(back_populates="directors")  # noqa: F821
