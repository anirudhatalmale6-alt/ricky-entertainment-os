"""Add independent demo hotels (2 per destination) so the by-destination market
study shows real averages instead of a single hotel per city.

Idempotent: skips if the marker hotel "Coral Reef Cancun" already exists. These
hotels are independent (no group), each with rooms/ADR/star + a monthly budget +
a venue and a few actuaciones, so the destination averages have N>1."""
import asyncio
from datetime import datetime

import httpx
from httpx import ASGITransport
from sqlalchemy import select

from app.db.session import AsyncSessionLocal, init_db
from app.main import app
from app.models.company import Company

MARKER = "Coral Reef Cancún"

# (name, city, rooms, ADR, star, entertainment_budget, occ%, venue, venue_cap)
HOTELS = [
    ("Coral Reef Cancún", "Cancún", 180, 2800, 4, 120000, 78, "Salón Coral", 300),
    ("Azul Grand Cancún", "Cancún", 260, 3500, 5, 200000, 85, "Gran Terraza", 450),
    ("Maya Beach Playa", "Playa del Carmen", 160, 2400, 4, 95000, 72, "Playa Lounge", 220),
    ("Turquesa Playa", "Playa del Carmen", 340, 3900, 5, 260000, 90, "Sky Deck", 400),
    ("Selva Tulum", "Tulum", 90, 3100, 4, 70000, 80, "Jungla Stage", 180),
    ("Jade Tulum", "Tulum", 120, 2900, 4, 85000, 76, "Cenote Lounge", 160),
]


def iso(y, m, d, h=21):
    return datetime(y, m, d, h, 0).replace(microsecond=0).isoformat()


async def _exists(name) -> bool:
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(Company).where(Company.name == name))).scalar_one_or_none() is not None


async def main():
    await init_db()
    if await _exists(MARKER):
        print("MARKET TOPUP SKIP: demo market hotels already present")
        return

    tr = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=tr, base_url="http://t", timeout=60) as c:
        tok = (await c.post("/api/v1/auth/login", json={"email": "admin@ricky.os", "password": "Admin123!"})).json()["access_token"]
        h = {"Authorization": f"Bearer {tok}"}

        # existing catalogue shows to book (rotate through different artists)
        shows = (await c.get("/api/v1/shows", headers=h)).json()
        shows = [s for s in shows if s.get("id")]
        if not shows:
            print("MARKET TOPUP SKIP: no shows to book")
            return

        made_h = made_b = 0
        si = 0  # rotating show index
        for idx, (name, city, rooms, adr, star, budget, occ, vname, vcap) in enumerate(HOTELS):
            comp = (await c.post("/api/v1/companies", json={
                "name": name, "city": city, "rooms": rooms, "avg_daily_rate": adr,
                "star_rating": star, "is_partner": False,
                "venues": [{"name": vname, "capacity": vcap}],
            }, headers=h)).json()
            await c.put(f"/api/v1/companies/{comp['id']}/budgets", json={
                "year": 2026, "month": 7, "entertainment_budget": budget, "occupancy_pct": occ}, headers=h)
            made_h += 1
            vid = comp["venues"][0]["id"]

            # 3 actuaciones on distinct days (May/Jun/Jul) so tarifa + heat map fill
            for j, (mm, dd) in enumerate([(5, 6 + idx), (6, 8 + idx), (7, 10 + idx)]):
                s = shows[si % len(shows)]; si += 1
                price = s.get("price_hotel") or s.get("base_price") or 15000
                r = await c.post("/api/v1/bookings", json={
                    "show_id": s["id"], "venue_id": vid, "starts_at": iso(2026, mm, dd), "agreed_price": price,
                }, headers=h)
                if r.status_code != 201:
                    continue
                bid = r.json()["id"]; made_b += 1
                await c.post(f"/api/v1/bookings/{bid}/confirm", headers=h)
                if mm < 7:  # past ones marked realizadas
                    await c.post(f"/api/v1/bookings/{bid}/attendance", json={
                        "headcount_start": int(vcap * 0.8), "headcount_end": int(vcap * 0.7)}, headers=h)
        print(f"MARKET TOPUP OK: +{made_h} hoteles, +{made_b} actuaciones")


asyncio.run(main())
