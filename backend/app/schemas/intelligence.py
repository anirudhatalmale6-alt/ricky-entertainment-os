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
    spend_per_room: float | None = None          # presupuesto / habitaciones
    spend_per_guest: float | None = None         # presupuesto / (habitaciones * ocupacion * huespedes_por_hab)
    city: str | None = None
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


class DemandRow(BaseModel):
    """One act category (or subcategory) ranked by how much it is being asked for."""
    key: str
    requests: int = 0            # solicitudes publicadas
    bookings: int = 0            # actuaciones contratadas
    booked_value: float = 0.0    # $ ya contratado (confirmadas+realizadas)
    demand_score: int = 0        # requests + bookings
    share_pct: float = 0.0       # % de la demanda total
    prev_score: int = 0          # demanda en el periodo anterior
    change_pct: float | None = None
    trend: str = "flat"          # up / down / flat


class DemandIntelligenceOut(BaseModel):
    """Supplier-facing view: 'que es lo que mas se esta pidiendo'."""
    window_days: int
    currency: str = "MXN"
    total_requests: int = 0
    total_bookings: int = 0
    top_categories: list[DemandRow] = []
    top_subcategories: list[DemandRow] = []
    note: str = ""


class MarketIntelligenceOut(BaseModel):
    year: int
    month: int
    currency: str = "MXN"
    property_count: int = 0
    market_avg_intensity_pct: float | None = None
    market_avg_spend_per_room: float | None = None    # promedio de mercado del gasto/habitacion
    market_avg_spend_per_guest: float | None = None   # promedio de mercado del gasto/huesped
    guests_per_room: float = 2.1                       # supuesto (configurable) para gasto/huesped
    total_entertainment_budget: float = 0.0
    total_entertainment_spend: float = 0.0
    properties: list[PropertyIntelligence] = []
    by_star_rating: list[StarTierStat] = []
    spend_by_category: list[CategoryTrend] = []
    note: str = ""


class ZoneStat(BaseModel):
    """One zone (ciudad) with its contracting activity and average tariff."""
    zone: str
    properties: int = 0          # hoteles activos en la zona
    bookings: int = 0            # actuaciones (no canceladas) en la ventana
    total_spend: float = 0.0     # $ contratado (confirmadas + realizadas)
    avg_price: float | None = None   # tarifa promedio por contratacion
    share_pct: float = 0.0       # % de las contrataciones del mercado (heat map)


class ZoneIntelligenceOut(BaseModel):
    """Geografia de la demanda: donde se contrata mas y donde es mas caro."""
    window_days: int
    currency: str = "MXN"
    total_bookings: int = 0
    zones: list[ZoneStat] = []
    note: str = ""


class DestinationStat(BaseModel):
    """Un destino (ciudad) con los PROMEDIOS de todos sus hoteles - estudio de
    mercado anonimo, sin señalar propiedades individuales."""
    zone: str
    hotels: int = 0                    # hoteles del destino (tamaño de muestra)
    avg_spend_per_room: float | None = None    # promedio de presupuesto/habitacion
    avg_spend_per_guest: float | None = None   # promedio de presupuesto/huesped
    avg_intensity_pct: float | None = None     # promedio de intensidad
    avg_occupancy_pct: float | None = None
    bookings: int = 0                  # contrataciones del destino (ventana)
    total_spend: float = 0.0
    avg_price: float | None = None     # tarifa promedio de contratacion
    share_pct: float = 0.0             # % de contrataciones del mercado (heat map)


class DestinationStudyOut(BaseModel):
    """Estudio de mercado por destino: promedios de todos los hoteles por ciudad."""
    year: int
    month: int
    window_days: int
    currency: str = "MXN"
    destinations_count: int = 0
    hotels_count: int = 0
    guests_per_room: float = 2.1
    market_avg_spend_per_room: float | None = None
    market_avg_spend_per_guest: float | None = None
    market_avg_price: float | None = None
    total_bookings: int = 0
    destinations: list[DestinationStat] = []
    note: str = ""


# --- Indicador 8: Estacionalidad de la demanda (curva del año) ---
class SeasonMonth(BaseModel):
    """Un mes de la curva de estacionalidad (mercado completo)."""
    year: int
    month: int              # 1-12
    label: str              # "Ene 26"
    bookings: int = 0       # actuaciones (no canceladas) que ocurren ese mes
    spend: float = 0.0      # $ contratado ese mes (confirmadas + realizadas)


class SeasonalityOut(BaseModel):
    """Estacionalidad de la demanda: en que meses se contrata mas entretenimiento
    en todo el mercado. Clave para planear a escala nacional."""
    currency: str = "MXN"
    months: list[SeasonMonth] = []
    peak_month: str | None = None      # mes mas alto (label)
    low_month: str | None = None       # mes mas bajo (label)
    total_bookings: int = 0
    note: str = ""


# --- Indicador 9: Rango de precios por categoria ---
class PriceRange(BaseModel):
    """Rango de precios de contratacion de una categoria/estilo (mercado)."""
    category: str
    bookings: int = 0       # muestra (contrataciones con precio)
    min_price: float | None = None
    avg_price: float | None = None
    max_price: float | None = None


class PriceRangesOut(BaseModel):
    """Cuanto cuesta contratar cada tipo de show: minimo, promedio y maximo del
    mercado, para saber si una tarifa esta cara o barata."""
    window_days: int
    currency: str = "MXN"
    categories: list[PriceRange] = []
    note: str = ""
