"""Give the demo artist (artist@demo.mx) a lively history so the artist Dashboard,
Facturación and Mi Perfil screens show real, populated data.

Idempotent: if the demo artist already has >=6 actuaciones, it does nothing, so
it's safe to run against the already-seeded live DB (it only touches the demo
artist and the demo hotels; David's own test account is never affected)."""
import asyncio
from datetime import datetime

import httpx
from httpx import ASGITransport
from sqlalchemy import func, select

from app.db.session import AsyncSessionLocal, init_db
from app.main import app
from app.models.artist import Artist
from app.models.booking import Booking
from app.models.company import Company
from app.models.user import User
from app.models.venue import Venue

DEMO_ARTIST_EMAIL = "artist@demo.mx"

SHOWS = [
    ("Cirque Nocturne", "Shows", "Circo & Acrobacias", 42000,
     "Espectáculo de circo y acrobacias aéreas con vestuario luminoso, ideal para grandes salones y galas."),
    ("Magia Estelar", "Shows", "Magia e Ilusionismo", 22000,
     "Show de magia e ilusionismo cercano y de escenario, perfecto para cenas y eventos corporativos."),
    ("Fuego & Luz", "Shows", "Espectaculos Visuales", 28000,
     "Espectáculo de fuego, pirotecnia fría y LED para playa y espacios abiertos."),
]

# (show, hotel, venue, y, m, d, price, action, headcounts)
BOOKINGS = [
    ("Cirque Nocturne", "Paraíso Playa", "Gran Salón", 2026, 5, 10, 42000, "attend", (540, 510)),
    ("Magia Estelar",   "Paraíso Cancún", "Teatro",     2026, 5, 24, 22000, "attend", (360, 340)),
    ("Fuego & Luz",     "Paraíso Tulum",  "Cenote Stage", 2026, 6, 8, 28000, "attend", (190, 175)),
    ("Cirque Nocturne", "Paraíso Cancún", "Teatro",     2026, 6, 22, 42000, "attend", (400, 390)),
    ("Magia Estelar",   "Paraíso Playa",  "Gran Salón", 2026, 7, 5, 22000, "attend", (520, 500)),
    ("Fuego & Luz",     "Paraíso Playa",  "Sky Lounge", 2026, 7, 20, 28000, "confirm", None),
    ("Cirque Nocturne", "Paraíso Cancún", "Teatro",     2026, 7, 26, 42000, "confirm", None),
    ("Magia Estelar",   "Paraíso Tulum",  "Cenote Stage", 2026, 7, 30, 22000, "pending", None),
]


def iso(y, m, d, h=21):
    return datetime(y, m, d, h, 0).replace(microsecond=0).isoformat()


async def _lookup():
    async with AsyncSessionLocal() as db:
        u = (await db.execute(select(User).where(User.email == DEMO_ARTIST_EMAIL))).scalar_one_or_none()
        if u is None:
            return None, None, 0
        a = (await db.execute(select(Artist).where(Artist.user_id == u.id))).scalar_one_or_none()
        if a is None:
            return None, None, 0
        rows = (await db.execute(
            select(Venue.id, Venue.name, Company.name).join(Company, Venue.company_id == Company.id)
        )).all()
        venue_by = {(comp, vn): vid for vid, vn, comp in rows}
        n = (await db.execute(select(func.count(Booking.id)).where(Booking.artist_id == a.id))).scalar_one()
        return a.id, venue_by, n


async def main():
    await init_db()
    aid, venue_by, existing = await _lookup()
    if aid is None:
        print("TOPUP SKIP: demo artist not found (run demo_seed first)")
        return
    if existing >= 6:
        print(f"TOPUP SKIP: demo artist already has {existing} actuaciones")
        return

    tr = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=tr, base_url="http://t", timeout=60) as c:
        tok = (await c.post("/api/v1/auth/login", json={"email": "admin@ricky.os", "password": "Admin123!"})).json()["access_token"]
        h = {"Authorization": f"Bearer {tok}"}

        # shows: create the ones this artist doesn't have yet
        have = {s["show_name"] for s in (await c.get(f"/api/v1/artists/{aid}/shows", headers=h)).json()}
        for name, cat, sub, price, desc in SHOWS:
            if name in have:
                continue
            await c.post(f"/api/v1/artists/{aid}/shows", json={
                "show_name": name, "category": cat, "subcategory": sub,
                "price_hotel": price, "duration_minutes": 90, "description": desc,
            }, headers=h)
        show_id = {s["show_name"]: s["id"] for s in (await c.get(f"/api/v1/artists/{aid}/shows", headers=h)).json()}

        made = 0
        for sn, hotel, vn, y, m, d, price, action, hc in BOOKINGS:
            sid = show_id.get(sn)
            vid = venue_by.get((hotel, vn))
            if not sid or not vid:
                continue
            r = await c.post("/api/v1/bookings", json={
                "show_id": sid, "venue_id": vid, "starts_at": iso(y, m, d), "agreed_price": price,
            }, headers=h)
            if r.status_code != 201:
                continue
            bid = r.json()["id"]
            made += 1
            if action in ("confirm", "attend"):
                await c.post(f"/api/v1/bookings/{bid}/confirm", headers=h)
            if action == "attend" and hc:
                await c.post(f"/api/v1/bookings/{bid}/attendance", json={
                    "headcount_start": hc[0], "headcount_end": hc[1]}, headers=h)
        print(f"TOPUP OK: +{made} actuaciones for demo artist (id={aid})")


asyncio.run(main())
