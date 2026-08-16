"""El caso que planteó David: un teatro chico lleno contra teatros grandes.

"si hay una propiedad de un teatro pequeño y se compara con teatros grandes,
siempre va a salir negativo, aunque su lleno esté completamente lleno".

Aquí se construye exactamente eso: el mismo proveedor llena un salón de 100 en
esta casa (95 de 100) y en otros hoteles trabaja en salones de 600 dejándolos a
la mitad (300 de 600). En gente por noche sale -68%; en llenado sale +45 puntos.
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta

DB = "/tmp/claude-1007/-home-freelancer/0ca5a747-3c2c-45ec-af78-b716325bcdba/scratchpad/llenado.db"
if os.path.exists(DB):
    os.remove(DB)
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB}"
sys.path.insert(0, "/var/lib/freelancer/projects/40528440/ricky-os/backend")

from app.core.security import hash_password  # noqa: E402
from app.db.session import AsyncSessionLocal, init_db  # noqa: E402
from app.models.artist import Artist  # noqa: E402
from app.models.booker import Booker  # noqa: E402
from app.models.booking import Booking  # noqa: E402
from app.models.company import Company  # noqa: E402
from app.models.enums import BookingStatus  # noqa: E402
from app.models.property_group import PropertyGroup  # noqa: E402
from app.models.show import Show  # noqa: E402
from app.models.user import Permission, Role, User  # noqa: E402
from app.models.venue import Venue  # noqa: E402

BASE = datetime(2026, 5, 4, 21, 0)


async def main():
    await init_db()
    async with AsyncSessionLocal() as db:
        perm = Permission(code="booking.manage", description="booking.manage")
        db.add(perm)
        await db.flush()
        rol = Role(name="hotel", description="hotel")
        rol.permissions = [perm]
        db.add(rol)
        await db.flush()

        grupo = PropertyGroup(name="Grupo Chico")
        db.add(grupo)
        await db.flush()
        chico = Company(name="Teatro Íntimo", company_type="hotel", group_id=grupo.id)
        ext_a = Company(name="Externo Uno", company_type="hotel")
        ext_b = Company(name="Externo Dos", company_type="hotel")
        for c in (chico, ext_a, ext_b):
            db.add(c)
        await db.flush()

        u = User(email="gerente@chico.mx", hashed_password=hash_password("x1234567"),
                 is_active=True, full_name="Gerencia Teatro Íntimo")
        u.roles = [rol]
        db.add(u)
        await db.flush()
        db.add(Booker(user_id=u.id, company_id=chico.id, position="Gerente"))

        # 100 butacas aquí; 600 en los hoteles de afuera.
        v_chico = Venue(company_id=chico.id, name="Sala Íntima", capacity=100)
        v_ea = Venue(company_id=ext_a.id, name="Gran Teatro", capacity=600)
        v_eb = Venue(company_id=ext_b.id, name="Auditorio", capacity=600)
        # Un segundo salón chico, para que el género tenga contra qué compararse.
        v_chico2 = Venue(company_id=chico.id, name="Sala Dos", capacity=100)
        for v in (v_chico, v_ea, v_eb, v_chico2):
            db.add(v)
        await db.flush()

        a1 = Artist(stage_name="Cuarteto Íntimo", is_active=True)
        a2 = Artist(stage_name="Otro del Género", is_active=True)
        db.add(a1); db.add(a2)
        await db.flush()
        s1 = Show(artist_id=a1.id, show_name="Cuerdas", category="Musica",
                  subcategory="Cuarteto", price_hotel=9000, is_active=True)
        s2 = Show(artist_id=a2.id, show_name="Otro cuarteto", category="Musica",
                  subcategory="Cuarteto", price_hotel=9000, is_active=True)
        db.add(s1); db.add(s2)
        await db.flush()

        def act(dia, venue, show, artist, precio, ini, fin):
            f = BASE + timedelta(days=dia)
            return Booking(
                show_id=show.id, venue_id=venue.id, company_id=venue.company_id,
                artist_id=artist.id, starts_at=f, agreed_price=precio, currency="MXN",
                status=BookingStatus.COMPLETED, notified_at=f - timedelta(days=8),
                confirmed_at=f - timedelta(days=7), headcount_start=ini, headcount_end=fin,
            )

        filas = [
            # AQUÍ: 95 de 100 butacas. Lleno.
            act(0,  v_chico, s1, a1, 9000, 95, 90),
            act(7,  v_chico, s1, a1, 9000, 96, 90),
            act(14, v_chico, s1, a1, 9000, 94, 88),
            # AFUERA: 300 de 600. Media entrada, pero MÁS gente en números.
            act(3,  v_ea, s1, a1, 30000, 300, 280),
            act(10, v_ea, s1, a1, 30000, 310, 290),
            act(17, v_eb, s1, a1, 30000, 290, 270),
            # Otro de su mismo género aquí, a media sala: el de arriba debe
            # salir por encima también contra su género.
            act(5,  v_chico2, s2, a2, 9000, 50, 45),
            act(12, v_chico2, s2, a2, 9000, 55, 50),
            act(19, v_chico2, s2, a2, 9000, 45, 40),
        ]
        for b in filas:
            db.add(b)
        await db.commit()
    print("listo:", DB)


asyncio.run(main())
