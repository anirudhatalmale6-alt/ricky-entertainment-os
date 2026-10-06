"""Precio efectivo de un show en una fecha concreta.

Un show tiene un precio público (``price_hotel``) y, encima, dos ajustes que
hasta ahora sólo se guardaban:

1. TEMPORADAS (``show_seasonal_rates``) — el calendario propio del artista:
   "Navidad +300 %", "Temporada baja −10 %"… Si la fecha de la actuación cae
   dentro de un periodo, el precio se ajusta. Un ``price`` absoluto en el
   periodo gana sobre el porcentaje.
2. TARIFA ESPECIAL DEL CLIENTE (``artist_client_rates``) — lo pactado con ese
   hotel o cadena. Un ``special_price`` absoluto manda sobre todo lo demás;
   un ``discount_pct`` se aplica sobre el precio ya ajustado por temporada.

3. PRECIO RECURRENTE (``price_corporate``) — la tarifa por volumen: cinco
   actuaciones del mismo show en 45 días. Quién la activa lo decide
   ``app/services/recurrente``; aquí sólo entra el importe, ya decidido.

Orden: base → temporada → tarifa del cliente → precio recurrente. Así el
descuento pactado con el hotel se respeta también en temporada alta.

Cuando coinciden una tarifa especial y el precio recurrente, GANA EL MÁS BAJO y
nunca se suman. Es lo que le propuse a David el 30/09 y está pendiente de que lo
confirme; mientras lo piensa vive aquí, en una sola línea (``min``), y sólo en
el demo. Lo que no está pendiente es que haya UN solo sitio que decida el
precio: el catálogo le enseñaba al hotel un número y al agendar se cobraba otro,
y eso no era una forma de hacerlo, era que dos partes del sistema decían cosas
distintas.
"""
from __future__ import annotations

from datetime import date, datetime


def _as_date(when) -> date | None:
    if when is None:
        return None
    if isinstance(when, datetime):
        return when.date()
    if isinstance(when, date):
        return when
    try:
        return datetime.fromisoformat(str(when).replace("Z", "")).date()
    except (TypeError, ValueError):
        return None


def season_for(show, when) -> object | None:
    """Periodo de temporada del show que cubre esa fecha (el primero que aplique)."""
    d = _as_date(when)
    if d is None or show is None:
        return None
    for rate in (getattr(show, "seasonal_rates", None) or []):
        start, end = _as_date(rate.start_date), _as_date(rate.end_date)
        if start and end and start <= d <= end:
            return rate
    return None


def travel_fee_for(show, distance_km) -> tuple[float, int] | None:
    """(monto, umbral) del extra por larga distancia si aplica a esa distancia.

    Es un monto FIJO para gasolina/casetas que el artista fija en su show: "si
    el destino está a más de 30 km, +$500". Se suma al final, después de
    temporadas y descuentos — el combustible cuesta lo mismo en temporada baja
    y no es negociable con un % de descuento pactado.
    """
    if distance_km is None or show is None:
        return None
    fee = getattr(show, "travel_fee", None)
    if fee is None or float(fee) <= 0:
        return None
    limit = int(getattr(show, "travel_fee_km", None) or 0)
    if limit <= 0 or float(distance_km) <= limit:
        return None
    return float(fee), limit


def effective_price(show, when=None, client_rate=None, distance_km=None,
                    recurrent_price=None) -> dict:
    """Precio efectivo + de dónde sale, para poder explicarlo en pantalla.

    Devuelve ``{price, base, season_label, season_pct, has_season,
    has_special_rate, has_recurrent, travel_fee, travel_fee_km}``. ``price`` es
    None si el show no tiene precio público.

    ``recurrent_price`` se pasa SÓLO cuando la tarifa por volumen ya está
    activada para ese hotel y esa fecha; esta función no la calcula, porque para
    saberlo hay que mirar las otras actuaciones y eso es una consulta.
    """
    base = float(show.price_hotel) if getattr(show, "price_hotel", None) is not None else None
    out = {
        "price": base, "base": base,
        "season_label": None, "season_pct": None,
        "has_season": False, "has_special_rate": False,
        "has_recurrent": False,
        "travel_fee": None, "travel_fee_km": None,
    }
    price = base

    season = season_for(show, when)
    if season is not None and price is not None:
        if season.price is not None:
            price = float(season.price)
        else:
            price = round(price * (1 + float(season.adjustment_pct or 0) / 100.0), 2)
        out["season_label"] = season.label
        out["season_pct"] = float(season.adjustment_pct or 0)
        out["has_season"] = price != base

    if client_rate is not None:
        if client_rate.special_price is not None:
            price = float(client_rate.special_price)
        elif client_rate.discount_pct is not None and price is not None:
            price = round(price * (1 - float(client_rate.discount_pct) / 100.0), 2)
        out["has_special_rate"] = price != base

    # Precio recurrente. Compite con lo ya calculado y gana el más bajo: si el
    # proveedor pactó con ese hotel algo mejor que su tarifa de volumen, lo
    # pactado se respeta. Nunca se encadenan los dos descuentos.
    if recurrent_price is not None and float(recurrent_price) > 0:
        tarifa = float(recurrent_price)
        if price is None or tarifa < price:
            price = tarifa
            out["has_recurrent"] = True

    # Un descuento mayor al 100 % dejaría el precio en negativo: se topa en 0.
    if price is not None and price < 0:
        price = 0.0

    # El extra por distancia va al final y por fuera de los descuentos.
    travel = travel_fee_for(show, distance_km)
    if travel is not None and price is not None:
        fee, limit = travel
        price = round(price + fee, 2)
        out["travel_fee"] = fee
        out["travel_fee_km"] = limit

    out["price"] = price
    return out
