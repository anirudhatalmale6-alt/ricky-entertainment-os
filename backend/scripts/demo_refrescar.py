"""Rellena la DEMO alrededor de HOY para que no parezca abandonada.

Por qué existe: seed_demo.py está anclada al 16/08/2026. Es a propósito (dos
corridas dan los mismos números), pero dos meses después la semana actual y las
siguientes salían casi vacías: cinco o seis actuaciones para toda una cadena,
casi todas pendientes. Un hotel que entra a ver la demo abre el calendario en
la semana de hoy y lo que ve es un tablero desierto.

Lo que hace, SÓLO sobre la base de la demo y sólo para las propiedades de la
cadena de demostración:

  * Desde el lunes de hace 3 semanas hasta el domingo dentro de 6 semanas.
  * Cada salón tiene actuación la mayoría de jueves a domingo y algunas noches
    entre semana.
  * Pasadas: realizadas, con aforo y, muchas, con su calificación.
  * Futuras: confirmadas en su mayoría y algunas pendientes, ya notificadas.

Reglas para no estropear nada:

  * Un salón y una noche que ya tienen una actuación NO se tocan. Lo que haya
    creado David a mano en la demo se queda tal cual.
  * Un mismo talento nunca sale dos veces la misma noche.
  * Todo lo que escribe lleva la marca MARCA en `notes`. Al volver a correrlo,
    primero borra lo que dejó la vez anterior (con sus reseñas, bitácora y
    avisos) y vuelve a generar la ventana nueva. Se puede correr cada semana.
  * No manda correos: la demo no tiene SMTP ni Mailgun, y esto ni siquiera pasa
    por la API.

Uso (en el servidor):
    PYTHONPATH=/opt/ricky_demo /opt/ricky_app/.venv/bin/python \\
        scripts/demo_refrescar.py /opt/ricky_demo/ricky_demo.db
    systemctl restart showma-demo     # rellena folios y tokens de las nuevas
"""
from __future__ import annotations

import random
import sys
from datetime import date, datetime, time, timedelta

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, selectinload

from app.models import Booking, Company, Review, Show, Venue
from app.models.property_budget import PropertyBudget
from app.models.booking_evento import BookingEvento
from app.models.notification import ArtistNotification
from app.services import pricing

DB = sys.argv[1] if len(sys.argv) > 1 else "./ricky_demo.db"
MARCA = "[demo-refresco]"
GRUPO_DEMO = 1                       # "Grupo Demo Riviera"

FIRMAS = [("Mariana López", "Gerente de Entretenimiento"),
          ("Jorge Ramírez", "Gerente de A&B"),
          ("Ana Castillo", "Coordinadora de Eventos"),
          ("Luis Herrera", "Gerente General")]
COMENTARIOS = {
    5: ["Excelente, los huéspedes se quedaron hasta el final.",
        "Llenó el salón y el ambiente fue muy bueno.",
        "Muy profesionales, llegaron con tiempo y sin contratiempos."],
    4: ["Muy buena actuación, buen repertorio.",
        "Cumplió bien, el público respondió.",
        "Buen show, repetiríamos."],
    3: ["Correcto, aunque el público se fue a mitad.",
        "Bien, pero llegó un poco justo de tiempo."],
}


def _lunes(d: date) -> date:
    return d - timedelta(days=d.weekday())


def main() -> None:
    hoy = datetime.now()
    ini = _lunes(hoy.date()) - timedelta(weeks=3)
    fin = _lunes(hoy.date()) + timedelta(weeks=6, days=6)
    # Semilla por ventana: dos corridas la misma semana dan lo mismo.
    R = random.Random(int(ini.strftime("%Y%m%d")))

    eng = create_engine(f"sqlite:///{DB}")
    with Session(eng) as s:
        # --- 1. Quitar lo que dejó la corrida anterior --------------------
        viejas = list(s.execute(
            select(Booking.id).where(Booking.notes == MARCA)).scalars())
        if viejas:
            s.execute(delete(Review).where(Review.booking_id.in_(viejas)))
            s.execute(delete(BookingEvento).where(BookingEvento.booking_id.in_(viejas)))
            s.execute(delete(ArtistNotification).where(ArtistNotification.booking_id.in_(viejas)))
            s.execute(delete(Booking).where(Booking.id.in_(viejas)))
            s.flush()

        # --- 2. Lo que hay ----------------------------------------------
        props = list(s.execute(select(Company).where(Company.group_id == GRUPO_DEMO)
                               .order_by(Company.id)).scalars())
        salones = list(s.execute(select(Venue).where(
            Venue.company_id.in_([p.id for p in props]),
            Venue.is_active.is_not(False)).order_by(Venue.id)).scalars())
        shows = list(s.execute(select(Show).options(selectinload(Show.seasonal_rates))
                               .where(Show.is_active.is_(True), Show.price_hotel > 0,
                                      Show.artist_id.is_not(None))).scalars())
        if not salones or not shows:
            print("No hay salones o shows en la cadena de demo; no se hace nada.")
            return

        ocupado: set[tuple[int, date]] = set()       # (venue, noche) con algo ya
        artista_noche: set[tuple[int, date]] = set()  # (artista, noche)
        for b in s.execute(select(Booking).where(
                Booking.starts_at >= datetime.combine(ini, time.min),
                Booking.starts_at <= datetime.combine(fin, time.max))).scalars():
            d = b.starts_at.date()
            if b.venue_id:
                ocupado.add((b.venue_id, d))
            if b.artist_id:
                artista_noche.add((b.artist_id, d))

        # --- 3. Generar ---------------------------------------------------
        nuevas, pasadas, resenas = 0, 0, 0
        d = ini
        while d <= fin:
            finde = d.weekday() >= 3                      # jueves a domingo
            for v in salones:
                if (v.id, d) in ocupado:
                    continue
                # Calibrado contra los meses reales de la demo (37-47 al mes en
                # toda la cadena). La primera versión metía ~100 al mes encima y
                # el gasto de octubre salía en $2.6M.
                if R.random() > (0.40 if finde else 0.10):
                    continue
                candidatos = [sh for sh in shows if (sh.artist_id, d) not in artista_noche]
                if not candidatos:
                    continue
                sh = R.choice(candidatos)
                inicio = datetime.combine(d, time(R.choice([19, 20, 20, 21, 21, 22]), 0))
                info = pricing.effective_price(sh, inicio)
                precio = info["price"] or float(sh.price_hotel)
                fuente = pricing.fuente_precio(info)
                ya_paso = inicio < hoy
                avisado = inicio - timedelta(days=R.randint(6, 25))
                b = Booking(
                    show_id=sh.id, venue_id=v.id, company_id=v.company_id,
                    artist_id=sh.artist_id, starts_at=inicio,
                    ends_at=inicio + timedelta(minutes=sh.duration_minutes or 90),
                    event_type="hotel", agreed_price=precio, price_source=fuente,
                    currency="MXN", commission_pct=15, notes=MARCA,
                    notified_at=avisado, invoice_paid=False, payout_paid=False,
                )
                if ya_paso:
                    cap = v.capacity or 120
                    gente = max(20, int(cap * min(1.0, max(0.3, R.gauss(0.68, 0.14)))))
                    ret = min(1.0, max(0.45, R.gauss(0.82, 0.08)))
                    b.status = "completed"
                    b.confirmed_at = avisado + timedelta(hours=R.randint(2, 30))
                    b.headcount_start, b.headcount_end = gente, int(gente * ret)
                    pasadas += 1
                else:
                    confirmada = R.random() < 0.75
                    b.status = "confirmed" if confirmada else "pending"
                    if confirmada:
                        b.confirmed_at = min(hoy, avisado + timedelta(hours=R.randint(2, 30)))
                s.add(b)
                s.flush()
                ocupado.add((v.id, d))
                artista_noche.add((sh.artist_id, d))
                nuevas += 1

                if ya_paso and R.random() < 0.72:
                    ret = b.headcount_end / max(b.headcount_start, 1)
                    nota = 5 if ret > 0.86 else 4 if ret > 0.72 else 3
                    firma = R.choice(FIRMAS)
                    s.add(Review(
                        booking_id=b.id, artist_id=b.artist_id, show_id=b.show_id,
                        company_id=b.company_id, rating=nota,
                        comment=R.choice(COMENTARIOS[nota]),
                        afluencia="alta" if ret > 0.85 else "media",
                        retencion="alta" if ret > 0.85 else "media",
                        author_name=firma[0], author_position=firma[1],
                        created_at=inicio + timedelta(days=R.randint(1, 3)),
                    ))
                    resenas += 1
            d += timedelta(days=1)

        # --- 4. Presupuestos que cuadren con el gasto -----------------------
        # Sólo había presupuesto cargado en UNA de las tres propiedades (~$254k
        # en octubre) para una cadena que siempre ha gastado ~$1M al mes, así
        # que el tablero decía "931 % sobre presupuesto" a quien abriera la
        # demo. Para cada propiedad y cada mes de la ventana se fija un
        # presupuesto tal que el uso quede en algo creíble: el mes pasado casi
        # agotado, el actual a buen ritmo y el que viene con margen.
        s.flush()
        uso_obj = {-1: 0.93, 0: 0.82, 1: 0.66}       # mes pasado / actual / siguiente
        mes_hoy = hoy.year * 12 + hoy.month - 1
        ppto = 0
        for p in props:
            for rel, objetivo in uso_obj.items():
                k = mes_hoy + rel
                anio, mes = k // 12, k % 12 + 1
                desde = datetime(anio, mes, 1)
                hasta = datetime(anio + (mes == 12), mes % 12 + 1, 1)
                gasto = sum(float(x or 0) for x in s.execute(select(Booking.agreed_price).where(
                    Booking.company_id == p.id, Booking.status != "cancelled",
                    Booking.starts_at >= desde, Booking.starts_at < hasta)).scalars())
                if gasto <= 0:
                    continue
                monto = round(gasto / (objetivo + R.uniform(-0.04, 0.04)), -4)
                fila = s.execute(select(PropertyBudget).where(
                    PropertyBudget.company_id == p.id, PropertyBudget.year == anio,
                    PropertyBudget.month == mes)).scalar_one_or_none()
                if fila is None:
                    s.add(PropertyBudget(company_id=p.id, year=anio, month=mes,
                                         entertainment_budget=monto, currency="MXN",
                                         notes=MARCA))
                else:
                    fila.entertainment_budget = monto
                ppto += 1

        s.commit()
        print(f"ventana: {ini} a {fin}")
        print(f"presupuestos ajustados (propiedad-mes): {ppto}")
        print(f"borradas de la corrida anterior: {len(viejas)}")
        print(f"actuaciones nuevas: {nuevas} (realizadas {pasadas}, por venir {nuevas - pasadas})")
        print(f"reseñas: {resenas}")


if __name__ == "__main__":
    main()
