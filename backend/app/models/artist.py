"""Artist model - the product of the marketplace."""
from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class Artist(Base, TimestampMixin):
    __tablename__ = "artists"

    id: Mapped[int] = mapped_column(primary_key=True)
    # An artist may (optionally) have a login account.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), unique=True)

    stage_name: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str] = mapped_column(String(80), index=True)  # musica en vivo, dj, show, etc.
    bio: Mapped[str | None] = mapped_column(Text)

    # Pricing (MXN)
    base_price: Mapped[float | None] = mapped_column(Numeric(12, 2))

    # Location
    city: Mapped[str | None] = mapped_column(String(120))
    region: Mapped[str | None] = mapped_column(String(120))
    country: Mapped[str] = mapped_column(String(80), default="Mexico")

    # Status / verification
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    rating: Mapped[float | None] = mapped_column(Numeric(3, 2))  # 0.00 - 5.00

    user: Mapped["User | None"] = relationship(back_populates="artist_profile")  # noqa: F821
