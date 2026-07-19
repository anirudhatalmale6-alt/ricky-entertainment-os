"""Freelancer-style requests board.

A ProductRequest ("solicitud") is a contratante asking the market for something
specific - a concept they don't find in the catalogue, a date they need covered,
a themed show for a season. Artists browse the open requests and answer with a
RequestProposal ("propuesta"). The hotel reviews the proposals and accepts one.

This is also the richest demand signal we have: every request records what the
market is asking for, which feeds the supplier trend analytics ("que es lo que
mas se esta pidiendo").
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum as SQLEnum,
    ForeignKey,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import ProposalStatus, RequestStatus


class ProductRequest(Base, TimestampMixin):
    __tablename__ = "product_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Who is asking. SET NULL so the request (and its demand signal) survives if
    # the hotel/booker record is later removed.
    company_id: Mapped[int | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), index=True
    )
    booker_id: Mapped[int | None] = mapped_column(
        ForeignKey("bookers.id", ondelete="SET NULL"), index=True
    )

    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    # What kind of act. Free of the catalogue, but tagged with the same taxonomy
    # so it aggregates cleanly in the demand trends.
    category: Mapped[str | None] = mapped_column(String(80), index=True)
    subcategory: Mapped[str | None] = mapped_column(String(80), index=True)

    event_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    city: Mapped[str | None] = mapped_column(String(120), index=True)
    region: Mapped[str | None] = mapped_column(String(120))

    budget_min: Mapped[float | None] = mapped_column(Numeric(12, 2))
    budget_max: Mapped[float | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="MXN")

    status: Mapped[RequestStatus] = mapped_column(
        SQLEnum(RequestStatus, values_callable=lambda e: [m.value for m in e]),
        default=RequestStatus.OPEN,
        index=True,
    )

    company: Mapped["Company | None"] = relationship()  # noqa: F821
    booker: Mapped["Booker | None"] = relationship()  # noqa: F821
    proposals: Mapped[list["RequestProposal"]] = relationship(
        back_populates="request", cascade="all, delete-orphan"
    )


class RequestProposal(Base, TimestampMixin):
    __tablename__ = "request_proposals"
    # One live proposal per artist per request (they can update it).
    __table_args__ = (
        UniqueConstraint("request_id", "artist_id", name="uq_proposal_request_artist"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("product_requests.id", ondelete="CASCADE"), index=True
    )
    artist_id: Mapped[int | None] = mapped_column(
        ForeignKey("artists.id", ondelete="SET NULL"), index=True
    )

    message: Mapped[str | None] = mapped_column(Text)
    proposed_price: Mapped[float | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="MXN")
    # Hasta 3 imágenes de referencia que el artista adjunta a su propuesta
    # (fotos del show, montaje, etc.). Lista de URLs servidas por /uploads.
    images: Mapped[list] = mapped_column(JSON, default=list)

    status: Mapped[ProposalStatus] = mapped_column(
        SQLEnum(ProposalStatus, values_callable=lambda e: [m.value for m in e]),
        default=ProposalStatus.PENDING,
        index=True,
    )

    request: Mapped["ProductRequest"] = relationship(back_populates="proposals")
    artist: Mapped["Artist | None"] = relationship()  # noqa: F821
