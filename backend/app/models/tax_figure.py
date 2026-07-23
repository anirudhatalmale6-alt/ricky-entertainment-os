"""Figuras fiscales (regímenes) — catálogo editable de impuestos.

Cada talento factura bajo una figura fiscal (régimen). Cada figura define la
comisión que retiene SHOWMA y las retenciones de ISR / IVA aplicables. El
administrador las edita desde el Master → Configuración → Impuestos, y el cálculo
de egresos usa estos porcentajes. Un talento puede tener una o varias figuras
(la mayoría comparte los mismos %, algunas cambian); aquí vive el catálogo con
sus porcentajes, revisado con el contador (David 2026-07-23).
"""
from __future__ import annotations

from sqlalchemy import Boolean, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class TaxFigure(Base, TimestampMixin):
    __tablename__ = "tax_figures"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))                     # nombre / régimen fiscal
    commission_pct: Mapped[float] = mapped_column(Float, default=0.0)  # comisión SHOWMA %
    isr_ret_pct: Mapped[float] = mapped_column(Float, default=0.0)     # retención ISR %
    iva_ret_pct: Mapped[float] = mapped_column(Float, default=0.0)     # retención IVA %
    notes: Mapped[str | None] = mapped_column(String(400))             # notas / casos especiales
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)   # figura por defecto
    active: Mapped[bool] = mapped_column(Boolean, default=True)
