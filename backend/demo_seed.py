"""Populate a realistic demo dataset (Grupo Paraíso) on top of the baseline seed.

Idempotent-ish: it checks for the "Grupo Paraíso" group and no-ops if it already
exists, so it is safe to call at every boot. Runs against whatever DATABASE_URL
the app is configured with, driving the real API (ASGITransport) so all the
business rules (commission snapshots, auto-actuacion on accept, ...) apply.

Demo logins created here:
  admin@ricky.os  / Admin123!   (baseline seed - full admin)
  hotel@demo.mx   / Demo1234!   (chain DIRECTOR of Grupo Paraíso -> exec dashboard)
  artist@demo.mx  / Demo1234!   (artist Luna Cirque - light artist view)
"""
import asyncio
from datetime import datetime

import httpx
from httpx import ASGITransport
from sqlalchemy import select

from app.main import app
from app.db.session import AsyncSessionLocal
from app.models.property_group import PropertyGroup


def iso(y, m, d, h=21):
    return datetime(y, m, d, h, 0).replace(microsecond=0).isoformat()


async def already_seeded() -> bool:
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(PropertyGroup).where(PropertyGroup.name == "Grupo Paraíso")
        )
        return res.scalar_one_or_none() is not None


async def main():
    if await already_seeded():
        print("DEMO SEED: already present, skipping")
        return

    tr = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=tr, base_url="http://t", timeout=60) as c:
        tok = (await c.post("/api/v1/auth/login", json={"email": "admin@ricky.os", "password": "Admin123!"})).json()["access_token"]
        h = {"Authorization": f"Bearer {tok}"}

        g = (await c.post("/api/v1/groups", json={"name": "Grupo Paraíso"}, headers=h)).json()["id"]

        hotels_spec = [
            ("Paraíso Cancún", "Cancún", 220, 3200, 5, True, 180000, 82,
             [("Teatro", 400), ("Lobby Bar", 120), ("Beach Club", 250)]),
            ("Paraíso Tulum", "Tulum", 140, 2600, 4, False, 90000, 74,
             [("Cenote Stage", 200), ("Pool Bar", 90)]),
            ("Paraíso Playa", "Playa del Carmen", 300, 4100, 5, True, 240000, 88,
             [("Gran Salón", 600), ("Sky Lounge", 150)]),
        ]
        hotels = {}
        for name, city, rooms, adr, star, partner, budget, occ, venues in hotels_spec:
            comp = (await c.post("/api/v1/companies", json={
                "name": name, "group_id": g, "city": city, "rooms": rooms,
                "avg_daily_rate": adr, "star_rating": star, "is_partner": partner,
                "venues": [{"name": vn, "capacity": vc} for vn, vc in venues],
            }, headers=h)).json()
            await c.put(f"/api/v1/companies/{comp['id']}/budgets", json={
                "year": 2026, "month": 7, "entertainment_budget": budget, "occupancy_pct": occ}, headers=h)
            hotels[name] = comp

        def venue(hotel, vname):
            return next(v["id"] for v in hotels[hotel]["venues"] if v["name"] == vname)

        artists_spec = [
            ("Mariachi Sol de México", [("Noche Mexicana", "Musica", "Mariachi", 18000)]),
            ("David Producciones", [("Jazz & Bossa", "Musica", "Solista", 12000),
                                     ("Ballet Folklórico", "Shows", "Danza", 15000)]),
            ("Luna Cirque", [("Cirque Nocturne", "Shows", "Circo & Acrobacias", 42000),
                              ("Magia Estelar", "Shows", "Magia e Ilusionismo", 22000)]),
            ("DJ Marea", [("Sunset Sessions", "Musica", "DJ", 9000)]),
        ]
        shows = {}
        for aname, specs in artists_spec:
            aid = (await c.post("/api/v1/artists", json={"stage_name": aname}, headers=h)).json()["id"]
            for sn, cat, sub, price in specs:
                sid = (await c.post(f"/api/v1/artists/{aid}/shows", json={
                    "show_name": sn, "category": cat, "subcategory": sub,
                    "price_hotel": price, "duration_minutes": 90}, headers=h)).json()["id"]
                shows[sn] = (sid, aid, price)

        bk = [
            ("Noche Mexicana", "Paraíso Cancún", "Teatro", 3, 18000, "attend", (320, 300)),
            ("Jazz & Bossa", "Paraíso Cancún", "Lobby Bar", 5, 12000, "attend", (95, 80)),
            ("Cirque Nocturne", "Paraíso Playa", "Gran Salón", 6, 42000, "attend", (540, 500)),
            ("Sunset Sessions", "Paraíso Tulum", "Pool Bar", 7, 9000, "attend", (85, 70)),
            ("Ballet Folklórico", "Paraíso Playa", "Sky Lounge", 9, 15000, "confirm", None),
            ("Magia Estelar", "Paraíso Cancún", "Beach Club", 11, 22000, "confirm", None),
            ("Noche Mexicana", "Paraíso Tulum", "Cenote Stage", 12, 18000, "attend", (180, 160)),
            ("Sunset Sessions", "Paraíso Playa", "Sky Lounge", 14, 9000, "confirm", None),
            ("Jazz & Bossa", "Paraíso Playa", "Sky Lounge", 16, 12000, "confirm", None),
            ("Cirque Nocturne", "Paraíso Cancún", "Teatro", 18, 42000, "confirm", None),
            ("Magia Estelar", "Paraíso Playa", "Gran Salón", 20, 22000, "pending", None),
            ("Noche Mexicana", "Paraíso Playa", "Gran Salón", 22, 18000, "pending", None),
            ("Ballet Folklórico", "Paraíso Cancún", "Teatro", 24, 15000, "confirm", None),
            ("Sunset Sessions", "Paraíso Cancún", "Beach Club", 26, 9000, "cancel", None),
        ]
        for sn, hotel, vn, day, price, action, hc in bk:
            sid = shows[sn][0]
            r = await c.post("/api/v1/bookings", json={
                "show_id": sid, "venue_id": venue(hotel, vn),
                "starts_at": iso(2026, 7, day), "agreed_price": price}, headers=h)
            if r.status_code != 201:
                continue
            bid = r.json()["id"]
            if action in ("confirm", "attend"):
                await c.post(f"/api/v1/bookings/{bid}/confirm", headers=h)
            if action == "attend" and hc:
                await c.post(f"/api/v1/bookings/{bid}/attendance", json={
                    "headcount_start": hc[0], "headcount_end": hc[1]}, headers=h)
            if action == "cancel":
                await c.post(f"/api/v1/bookings/{bid}/cancel?reason=Clima", headers=h)

        reqs = [
            ("Paraíso Playa", "Show de fuego para la playa", "Shows", "Espectaculos Visuales", "Playa del Carmen", 20000, 35000),
            ("Paraíso Cancún", "Mariachi para boda VIP", "Musica", "Mariachi", "Cancún", 15000, 25000),
            ("Paraíso Tulum", "Stand up comedy fin de semana", "Shows", "Comedia & Stand Up", "Tulum", 8000, 14000),
            ("Paraíso Cancún", "DJ para pool party", "Musica", "DJ", "Cancún", 7000, 12000),
            ("Paraíso Playa", "Fotógrafo para gala anual", "Fotografia y Video", "Fotografia", "Playa del Carmen", 10000, 18000),
        ]
        rids = []
        for hotel, title, cat, sub, city, bmin, bmax in reqs:
            rid = (await c.post("/api/v1/requests", json={
                "company_id": hotels[hotel]["id"], "title": title, "category": cat,
                "subcategory": sub, "city": city, "budget_min": bmin, "budget_max": bmax}, headers=h)).json()["id"]
            rids.append(rid)

        a_luna = shows["Cirque Nocturne"][1]
        a_mar = shows["Noche Mexicana"][1]
        await c.post(f"/api/v1/requests/{rids[0]}/proposals", json={"artist_id": a_luna, "message": "Show de fuego 25 min, 4 artistas", "proposed_price": 28000}, headers=h)
        await c.post(f"/api/v1/requests/{rids[0]}/proposals", json={"artist_id": shows['Magia Estelar'][1], "message": "Pirotecnia fría + LED", "proposed_price": 31000}, headers=h)
        p = (await c.post(f"/api/v1/requests/{rids[1]}/proposals", json={"artist_id": a_mar, "message": "Mariachi 10 elementos", "proposed_price": 20000}, headers=h)).json()
        await c.post(f"/api/v1/requests/{rids[1]}/proposals/{p['id']}/accept", headers=h)

        conv1 = (await c.post("/api/v1/conversations", json={
            "artist_id": a_luna, "company_id": hotels["Paraíso Playa"]["id"], "request_id": rids[0],
            "subject": "Show de fuego"}, headers=h)).json()["id"]
        for role, body in [("company", "Hola Luna, vimos su propuesta del show de fuego, se ve increíble"),
                            ("artist", "¡Gracias! Podemos adaptarlo al espacio de la playa sin problema"),
                            ("company", "Perfecto. ¿Incluye montaje y seguridad?"),
                            ("artist", "Sí, todo incluido. Llegamos 3 horas antes para montar")]:
            await c.post(f"/api/v1/conversations/{conv1}/messages", json={"sender_role": role, "body": body}, headers=h)

        conv2 = (await c.post("/api/v1/conversations", json={
            "artist_id": a_mar, "company_id": hotels["Paraíso Cancún"]["id"],
            "subject": "Mariachi boda"}, headers=h)).json()["id"]
        for role, body in [("company", "Buen día, confirmamos el mariachi para la boda del 20"),
                           ("artist", "Confirmado, llegamos puntuales con los 10 elementos"),
                           ("artist", "¿Nos comparten el acceso de proveedores?")]:
            await c.post(f"/api/v1/conversations/{conv2}/messages", json={"sender_role": role, "body": body}, headers=h)

        conv3 = (await c.post("/api/v1/conversations", json={
            "artist_id": shows["Sunset Sessions"][1], "company_id": hotels["Paraíso Tulum"]["id"],
            "subject": "Pool party"}, headers=h)).json()["id"]
        await c.post(f"/api/v1/conversations/{conv3}/messages", json={"sender_role": "artist", "body": "Hola, tengo disponibilidad para el pool party, ¿qué fecha manejan?"}, headers=h)

        # --- real login accounts (artist + hotel DIRECTOR) for the UI demo -----
        def bearer(t):
            return {"Authorization": f"Bearer {t}"}

        art_tok = (await c.post("/api/v1/auth/register/artist", json={
            "email": "artist@demo.mx", "full_name": "Luna Cirque", "password": "Demo1234!",
            "stage_name": "Luna Cirque", "base_city": "Cancún"})).json()["access_token"]
        art_aid = (await c.get("/api/v1/auth/me", headers=bearer(art_tok))).json()["artist_id"]

        # hotel@demo.mx = DIRECTOR of Grupo Paraíso (group_id, no single company) so
        # logging in as "hotel" lands on the consolidated exec dashboard of all 3.
        await c.post("/api/v1/auth/register/contratante", json={
            "email": "hotel@demo.mx", "full_name": "Ana Torres", "password": "Demo1234!",
            "group_id": g, "position": "Directora de entretenimiento"})

        # Give the demo artist a live actuacion + chat tied to a real hotel, so
        # their scoped /mine views show real content on login.
        dreq = (await c.post("/api/v1/requests", json={
            "company_id": hotels["Paraíso Cancún"]["id"], "title": "Show de fuego para gala", "category": "Shows",
            "subcategory": "Espectaculos Visuales", "city": "Cancún",
            "event_date": iso(2026, 7, 19), "budget_min": 20000, "budget_max": 35000}, headers=h)).json()
        dprop = (await c.post(f"/api/v1/requests/{dreq['id']}/proposals", json={
            "artist_id": art_aid, "message": "Show de fuego 25 min, 4 artistas", "proposed_price": 28000}, headers=h)).json()
        await c.post(f"/api/v1/requests/{dreq['id']}/proposals/{dprop['id']}/accept", headers=h)

        dconv = (await c.post("/api/v1/conversations", json={
            "artist_id": art_aid, "company_id": hotels["Paraíso Cancún"]["id"], "request_id": dreq["id"],
            "subject": "Show de fuego"}, headers=h)).json()["id"]
        for role, body in [("company", "Hola Luna, aceptamos tu propuesta del show de fuego"),
                           ("artist", "¡Excelente! Llegamos 3 horas antes para montar"),
                           ("company", "Perfecto, te paso el acceso de proveedores por aquí")]:
            await c.post(f"/api/v1/conversations/{dconv}/messages", json={"sender_role": role, "body": body}, headers=h)

        print("DEMO SEED OK  (group id=%s, 3 hoteles, demo logins ready)" % g)


if __name__ == "__main__":
    asyncio.run(main())
