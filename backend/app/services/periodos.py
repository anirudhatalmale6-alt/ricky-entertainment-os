"""Periodos de facturación (quincenas).

David, 2026-08-12: "al hotel se le van a enviar los 15 y los 30 de cada mes, y a
los músicos igual… un atraso y tendremos que pagar dinero que aún no tenemos".
De ahí sale todo este módulo: el mes se parte en dos quincenas, cada una cierra
en su fecha de corte y el depósito sale 10 días después del corte.

    Q1 = del 1 al 15   -> corta el día 15
    Q2 = del 16 al fin -> corta el ÚLTIMO día del mes

Ojo con el "30": en un mes de 31 días el 31 quedaría fuera de toda quincena, y
en febrero el 30 no existe. Por eso el segundo corte es el último día del mes —
que en la mayoría de los meses ES el 30 o el 31, y así ninguna actuación se
queda sin periodo.

Todo aquí son funciones puras sobre fechas: no tocan la base ni Facturama, para
poder probarlas solas y para que el mismo cálculo lo usen el cierre automático,
la pantalla del músico y la del hotel.
"""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta

# Días entre la fecha de corte y el depósito.
PAYMENT_DELAY_DAYS = 10

_KEY_RE = re.compile(r"^(\d{4})-(\d{2})-Q([12])$")

_MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def as_date(when) -> date | None:
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


def last_day(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def key_for(when) -> str | None:
    """Clave del periodo al que pertenece una fecha: "2026-08-Q1"."""
    d = as_date(when)
    if d is None:
        return None
    return f"{d.year}-{d.month:02d}-Q{1 if d.day <= 15 else 2}"


def parse(key: str) -> tuple[int, int, int]:
    m = _KEY_RE.match((key or "").strip())
    if not m:
        raise ValueError(f"Periodo inválido: {key!r}. Se espera 'YYYY-MM-Q1' o 'YYYY-MM-Q2'.")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def range_of(key: str) -> tuple[date, date]:
    """(primer día, último día) del periodo, ambos incluidos."""
    y, m, q = parse(key)
    if q == 1:
        return date(y, m, 1), date(y, m, 15)
    return date(y, m, 16), date(y, m, last_day(y, m))


def cutoff(key: str) -> date:
    """Fecha de corte: el último día del periodo."""
    return range_of(key)[1]


def payment_date(key: str) -> date:
    """Fecha de depósito: 10 días naturales después del corte."""
    return cutoff(key) + timedelta(days=PAYMENT_DELAY_DAYS)


def label(key: str) -> str:
    """Texto para pantalla: "1–15 de agosto de 2026"."""
    y, m, _ = parse(key)
    ini, fin = range_of(key)
    return f"{ini.day}–{fin.day} de {_MESES[m - 1]} de {y}"


def short_label(key: str) -> str:
    """Texto corto para tablas: "Ago 2026 · 1ª quincena"."""
    y, m, q = parse(key)
    return f"{_MESES[m - 1][:3].capitalize()} {y} · {q}ª quincena"


def is_closed(key: str, today=None) -> bool:
    """¿Ya pasó la fecha de corte de este periodo?"""
    t = as_date(today) or date.today()
    return cutoff(key) <= t


def previous(key: str) -> str:
    """El periodo anterior a éste."""
    y, m, q = parse(key)
    if q == 2:
        return f"{y}-{m:02d}-Q1"
    if m == 1:
        return f"{y - 1}-12-Q2"
    return f"{y}-{m - 1:02d}-Q2"


def last_closed(today=None) -> str:
    """El periodo cerrado más reciente — el que toca facturar."""
    t = as_date(today) or date.today()
    actual = key_for(t)
    return actual if is_closed(actual, t) else previous(actual)


def keys_between(desde, hasta) -> list[str]:
    """Todas las claves de periodo entre dos fechas, en orden."""
    a, b = as_date(desde), as_date(hasta)
    if a is None or b is None or a > b:
        return []
    out: list[str] = []
    k = key_for(a)
    while True:
        out.append(k)
        if k == key_for(b):
            break
        _, fin = range_of(k)
        k = key_for(fin + timedelta(days=1))
    return out


def info(key: str, today=None) -> dict:
    """Todo lo que la pantalla necesita saber de un periodo."""
    ini, fin = range_of(key)
    return {
        "period": key,
        "label": label(key),
        "short": short_label(key),
        "start": ini.isoformat(),
        "end": fin.isoformat(),
        "cutoff": cutoff(key).isoformat(),
        "payment_date": payment_date(key).isoformat(),
        "closed": is_closed(key, today),
    }
