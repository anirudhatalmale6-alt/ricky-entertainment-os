"""Market Intelligence output schemas.

Turns the property profile (rooms + ADR + occupancy) and the real bookings into
a benchmarking view: how much of each property's room revenue goes into
entertainment, how that compares to the market and to same-star peers, how the
entertainment spend splits by star rating, and which act categories are rising
or falling month over month.
"""
from __future__ import annotations

from pydantic import BaseModel


class PropertyIntelligence(BaseModel):
    id: int
    name: str
    star_rating: int | None = None
    rooms: int | None = None
    avg_daily_rate: float | None = None
    occupancy_pct: float | None = None
    est_room_revenue: float | None = None       # rooms * ADR * occ% * 30 (mes)
    entertainment_budget: float | None = None    # gasto cargado en el mes
    entertainment_spend: float = 0.0             # actuaciones reales (confirmadas+realizadas)
    intensity_pct: float | None = None           # % de la facturacion que va a entretenimiento
    vs_market_pct: float | None = None           # diferencia vs promedio de mercado
    vs_star_peers_pct: float | None = None        # diferencia vs pares de su categoria
    is_partner: bool = False


class StarTierStat(BaseModel):
    star_rating: int
    properties: int
    avg_intensity_pct: float | None = None
    total_spend: float = 0.0
    spend_share_pct: float = 0.0                  # % del gasto total del mercado


class CategoryTrend(BaseModel):
    category: str
    spend: float = 0.0
    prev_spend: float = 0.0
    delta: float = 0.0
    change_pct: float | None = None              # None cuando el mes previo fue 0
    share_pct: float = 0.0
    trend: str = "flat"                          # up / down / flat


class MarketIntelligenceOut(BaseModel):
    year: int
    month: int
    currency: str = "MXN"
    property_count: int = 0
    market_avg_intensity_pct: float | None = None
    total_entertainment_budget: float = 0.0
    total_entertainment_spend: float = 0.0
    properties: list[PropertyIntelligence] = []
    by_star_rating: list[StarTierStat] = []
    spend_by_category: list[CategoryTrend] = []
    note: str = ""
