#!/usr/bin/env python
"""Cierre automático de la quincena — pensado para correr UNA VEZ AL DÍA.

    /opt/ricky_app/.venv/bin/python -m scripts.cerrar_periodo

No hace falta que corra exactamente el día 15 o el 30: mira cuál es la última
quincena cerrada y factura lo que quede pendiente de ella. Como sólo toma
actuaciones con `cfdi_id` en NULL, correrlo de más NO vuelve a facturar nada —
que es la garantía que pidió David ("un atraso y tendremos que pagar dinero que
aún no tenemos"). Si un día falla el servidor, el del día siguiente lo recupera.

Con `--periodo 2026-08-Q1` se cierra uno concreto (para recuperar un atraso), y
con `--dry-run` sólo se enseña lo que haría.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings          # noqa: E402
from app.db.session import AsyncSessionLocal, init_db  # noqa: E402
from app.services import facturacion, periodos  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("showma.cierre")


async def run(period: str | None, dry_run: bool) -> int:
    await init_db()
    key = period or periodos.last_closed()
    try:
        info = periodos.info(key)
    except ValueError as exc:
        log.error("%s", exc)
        return 2

    if not info["closed"]:
        log.info("El periodo %s aún no cierra (corta el %s). Nada que hacer.",
                 info["short"], info["cutoff"])
        return 0

    async with AsyncSessionLocal() as db:
        pendientes = await facturacion.pending_bookings_for_period(db, key)
        if not pendientes:
            log.info("Periodo %s: no hay actuaciones pendientes de facturar.", info["short"])
            return 0

        importe = sum(float(b.agreed_price or 0) for b in pendientes)
        pares = {(b.artist_id, b.company_id) for b in pendientes if b.artist_id and b.company_id}
        log.info("Periodo %s (%s): %d actuaciones pendientes, %d factura(s), $%.2f. Depósito el %s.",
                 info["short"], info["label"], len(pendientes), len(pares), importe,
                 info["payment_date"])

        if dry_run:
            log.info("--dry-run: no se emite nada.")
            return 0
        if not settings.FACTURAMA_ENABLED:
            log.warning("FACTURAMA_ENABLED está en false: no se puede timbrar todavía.")
            return 1

        resumen = await facturacion.close_period(db, key)
        log.info("Emitidas: %d · con error: %d · sin músico u hotel: %d",
                 resumen["facturas_emitidas"], resumen["facturas_con_error"],
                 len(resumen["sin_musico_u_hotel"]))
        for e in resumen["errores"]:
            log.error("  artista %s / hotel %s: %s", e["artist_id"], e["company_id"], e["error"])
        return 1 if resumen["facturas_con_error"] else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Cierra la quincena y emite sus facturas.")
    ap.add_argument("--periodo", help="Quincena concreta, p. ej. 2026-08-Q1")
    ap.add_argument("--dry-run", action="store_true", help="Sólo enseña lo que haría")
    args = ap.parse_args()
    return asyncio.run(run(args.periodo, args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
