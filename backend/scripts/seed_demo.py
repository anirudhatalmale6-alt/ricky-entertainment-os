"""Siembra la base del entorno DEMO de SHOWMA (base aparte, no toca producción).

Para qué: David necesita enseñar la plataforma con datos suficientes para que
las comparativas de 'Análisis de desempeño' salgan llenas. En producción no
salen porque casi ningún proveedor ha trabajado todavía en dos hoteles
distintos — y esos datos NO se inventan en la base real.

Todo lo de aquí vive en /opt/ricky_demo/ricky_demo.db, una base propia que
sirve otra instancia de la misma aplicación en /demo. Ni un registro de este
archivo llega a la base de producción.

Los números salen de un generador con semilla fija: dos corridas dan lo mismo,
así que una captura de pantalla de hoy sigue valiendo el mes que viene.

Uso:  python seed_demo.py /ruta/ricky_demo.db
"""
from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.base import Base
from app.models import (
    Artist,
    Booker,
    Booking,
    Company,
    Permission,
    PropertyGroup,
    Review,
    Role,
    Show,
    User,
    Venue,
)

DB = sys.argv[1] if len(sys.argv) > 1 else "./ricky_demo.db"
CLAVE = "Demo2026!"
R = random.Random(20260816)          # semilla fija: la demo es siempre la misma

HOY = datetime(2026, 8, 16, 12, 0)

PERMISOS = [
    ("user.manage", "Create / edit / deactivate users"),
    ("artist.manage", "Approve and manage artists"),
    ("company.manage", "Manage hotels / venues"),
    ("booking.manage", "Manage bookings and requests"),
    ("invoice.manage", "Manage CFDI invoicing"),
    ("payment.manage", "Manage payments and settlements"),
    ("report.view", "View reports and BI"),
]
ROLES = {
    "admin": [c for c, _ in PERMISOS],
    "finance": ["invoice.manage", "payment.manage", "report.view"],
    "booker": ["booking.manage", "report.view"],
    "artist": [],
}

# (nombre, ciudad, cuartos, estrellas, [(salón, aforo)])
# Los aforos se parecen a propósito entre propiedades: la convocatoria se compara
# en gente por noche, y si un hotel tuviera un teatro de 800 y otro una terraza de
# 120, la comparativa mediría el tamaño del salón y no el tirón del artista.
CADENA = [
    ("Riviera Cancún", "Cancún", 620, 5,
     [("Gran Salón", 520), ("Playa Lounge", 230), ("Sky Bar", 215)]),
    ("Riviera Tulum", "Tulum", 280, 5,
     [("Teatro Selva", 460), ("Cenote Lounge", 200)]),
    ("Riviera Playa", "Playa del Carmen", 410, 4,
     [("Salón Coral", 500), ("Terraza Quinta", 240)]),
]
SUELTOS = [
    ("Coral Bay Resort", "Cancún", 350, 4, [("Salón Turquesa", 480), ("Beach Club", 220)]),
    ("Selva Hotel & Spa", "Tulum", 190, 4, [("Jungla Stage", 440), ("Palapa Mayor", 190)]),
    ("Azul Palace", "Cancún", 700, 5, [("Gran Teatro", 560), ("Roof 21", 210)]),
    ("Marina Suites", "Puerto Aventuras", 220, 4, [("Salón Marina", 470), ("Muelle 7", 200)]),
    ("Sunset Cove", "Playa del Carmen", 160, 4, [("Terraza Sunset", 450), ("Cala Bar", 180)]),
]

# (nombre, categoría, subcategoría, ciudad, [(show, precio, minutos)])
# Cada género va REPETIDO al menos dos veces: la columna "vs. promedio de su
# género aquí" compara a un proveedor contra los otros de su mismo género en la
# misma casa, y si cada uno fuera único esa columna saldría vacía entera.
TALENTOS = [
    ("Trío Mar Abierto", "Musica", "Trio", "Cancún",
     [("Boleros de la Costa", 18000, 90)]),
    ("Sonora Costa Azul", "Musica", "Banda", "Cancún",
     [("Noche Sonora", 42000, 120), ("Set Tropical", 28000, 75)]),
    ("DJ Marea", "Musica", "DJ", "Playa del Carmen",
     [("Sunset Session", 16000, 180)]),
    ("Mariachi Sol de Playa", "Musica", "Mariachi", "Cancún",
     [("Serenata Mexicana", 24000, 60)]),
    ("Ana Sol", "Musica", "Solista", "Tulum",
     [("Voz y Guitarra", 12000, 90)]),
    ("Dueto Luna y Sal", "Musica", "Dueto", "Playa del Carmen",
     [("Acústico Caribe", 14000, 90)]),
    ("Cirque Aurora", "Shows", "Circo & Acrobacias", "Cancún",
     [("Aurora Nocturna", 68000, 55), ("Aéreos & Telas", 45000, 40)]),
    ("Fuego Maya", "Shows", "Espectaculos Visuales", "Tulum",
     [("Ritual de Fuego", 38000, 45)]),
    ("Ballet Caribe", "Shows", "Danza", "Playa del Carmen",
     [("Raíces del Caribe", 32000, 50)]),
    ("Magia Zafiro", "Shows", "Magia e Ilusionismo", "Cancún",
     [("Ilusión Zafiro", 26000, 60)]),
    ("Los Camaleones", "Shows", "Comedia & Stand Up", "Cancún",
     [("Comedia de Playa", 22000, 70)]),
    ("Piratas del Caribe Kids", "Shows", "Infantiles y Familiares", "Cancún",
     [("Abordaje Pirata", 19000, 50)]),
    # --- segundos (y terceros) de cada género -----------------------------
    ("Los Jarochos", "Musica", "Trio", "Playa del Carmen",
     [("Son Jarocho", 16000, 90)]),
    ("Banda Malecón", "Musica", "Banda", "Playa del Carmen",
     [("Fiesta Malecón", 38000, 110)]),
    ("DJ Selva", "Musica", "DJ", "Tulum",
     [("Deep Jungle", 18000, 180)]),
    ("Mariachi Quintana", "Musica", "Mariachi", "Cancún",
     [("Noche de Mariachi", 26000, 60)]),
    ("Carla Vento", "Musica", "Solista", "Cancún",
     [("Piano y Voz", 15000, 90)]),
    ("Nico Arrecife", "Musica", "Solista", "Playa del Carmen",
     [("Guitarra al Atardecer", 11000, 100)]),
    ("Dueto Sal y Miel", "Musica", "Dueto", "Cancún",
     [("Set Romántico", 13000, 90)]),
    ("Circo Nube", "Shows", "Circo & Acrobacias", "Playa del Carmen",
     [("Nube de Seda", 52000, 45)]),
    ("Luz de Chichén", "Shows", "Espectaculos Visuales", "Cancún",
     [("Mapping Maya", 44000, 40)]),
    ("Danza Sirena", "Shows", "Danza", "Cancún",
     [("Sirenas del Golfo", 29000, 45)]),
    ("Ilusionista Kai", "Shows", "Magia e Ilusionismo", "Tulum",
     [("Kai en Vivo", 21000, 55)]),
    ("Comedia Costeña", "Shows", "Comedia & Stand Up", "Playa del Carmen",
     [("Micrófono Abierto", 17000, 70)]),
    ("Tesoro Kids", "Shows", "Infantiles y Familiares", "Tulum",
     [("La Isla del Tesoro", 16000, 45)]),
]

# El comentario va con la calificación: una reseña de 3 estrellas con un texto
# entusiasta se lee falsa en cuanto alguien la mira de cerca.
COMENTARIOS = {
    5: [
        "El salón se llenó y la gente se quedó hasta el final. Repetimos seguro.",
        "A los huéspedes les encantó. Nos pidieron la fecha del próximo.",
        "De lo mejor que hemos tenido esta temporada en el teatro.",
        "Impecables. Ya los agendamos para la temporada alta.",
        "Excelente montaje. Nos ayudaron con la logística de la terraza sin cobrar extra.",
    ],
    4: [
        "Muy profesionales, llegaron dos horas antes a montar y no tuvimos un solo problema.",
        "Cumplieron con lo pactado. El público de familias respondió muy bien.",
        "Muy puntuales y muy correctos con el equipo del hotel.",
        "Nos resolvieron un cambio de salón a última hora sin poner un pero.",
    ],
    3: [
        "Buen show, aunque el arranque se retrasó unos minutos por el audio.",
        "Para nuestro público hubiera funcionado mejor un set más corto.",
        "El público bajó bastante en la segunda hora; el show en sí estuvo bien.",
        "Cumplieron, pero tuvimos que insistir con el montaje del escenario.",
    ],
}
FIRMAS = [
    ("Mariana Rojas", "Gerente de Entretenimiento"),
    ("Luis Cabrera", "Coordinador de Actividades"),
    ("Paula Méndez", "Gerente de Alimentos y Bebidas"),
    ("Sergio Landa", "Director de Operaciones"),
    ("Idalia Cruz", "Jefa de Grupos y Convenciones"),
]


def sello(texto: str) -> int:
    """Número estable a partir de un texto (hash() de Python no lo es)."""
    n = 0
    for ch in texto:
        n = (n * 31 + ord(ch)) % 100003
    return n


def main() -> None:
    eng = create_engine("sqlite:///" + DB, future=True)
    Base.metadata.create_all(eng)
    s = Session(eng)

    # --- roles y permisos, iguales a los de producción -------------------
    perms = {c: Permission(code=c, description=d) for c, d in PERMISOS}
    s.add_all(perms.values())
    roles = {}
    for nombre, codigos in ROLES.items():
        r = Role(name=nombre, description=f"{nombre.capitalize()} role")
        r.permissions = [perms[c] for c in codigos]
        roles[nombre] = r
        s.add(r)
    s.flush()

    # --- propiedades -----------------------------------------------------
    grupo = PropertyGroup(name="Grupo Demo Riviera", contact_email="demo@showma.mx")
    s.add(grupo)
    s.flush()

    props: list[Company] = []
    salones: dict[int, list[Venue]] = {}
    for de_la_cadena, (nombre, ciudad, cuartos, estrellas, vs) in (
        [(True, x) for x in CADENA] + [(False, x) for x in SUELTOS]
    ):
        c = Company(
            name=nombre, company_type="hotel", city=ciudad, region="Quintana Roo",
            country="México", rooms=cuartos, star_rating=estrellas,
            group_id=grupo.id if de_la_cadena else None,
            is_all_inclusive=True, agreed_payment_days=30,
        )
        s.add(c)
        s.flush()
        props.append(c)
        salones[c.id] = []
        for vn, cap in vs:
            v = Venue(company_id=c.id, name=vn, capacity=cap, is_active=True,
                      ambiance_type="Salón" if cap > 200 else "Terraza")
            s.add(v)
            salones[c.id].append(v)
    s.flush()

    # --- talento ---------------------------------------------------------
    artistas: list[Artist] = []
    shows: dict[int, list[Show]] = {}
    for nombre, cat, sub, ciudad, ss in TALENTOS:
        a = Artist(
            stage_name=nombre, artist_type=cat, city=ciudad, region="Quintana Roo",
            country="México", base_city=ciudad, is_active=True, is_verified=True,
            available_to_travel=True, years_experience=R.randint(3, 18),
            bio=f"{nombre} — perfil de demostración para presentar la plataforma.",
        )
        s.add(a)
        s.flush()
        artistas.append(a)
        shows[a.id] = []
        for sn, precio, mins in ss:
            sh = Show(artist_id=a.id, show_name=sn, category=cat, subcategory=sub,
                      duration_minutes=mins, base_price=precio, price_hotel=precio,
                      is_active=True,
                      description=f"{sn} — show de demostración ({sub}).")
            s.add(sh)
            shows[a.id].append(sh)
    s.flush()

    # --- usuarios --------------------------------------------------------
    def usuario(email, nombre, rol, **kw):
        u = User(email=email, full_name=nombre, hashed_password=hash_password(CLAVE),
                 is_active=True, role_id=roles[rol].id, totp_enabled=False, **kw)
        s.add(u)
        s.flush()
        return u

    u_admin = usuario("demo.admin@showma.mx", "Demo Administración", "admin", is_superuser=True)
    u_dir = usuario("demo.director@showma.mx", "Demo Dirección de Grupo", "booker")
    u_ger = usuario("demo.hotel@showma.mx", "Demo Gerencia Riviera Cancún", "booker")
    u_art = usuario("demo.artista@showma.mx", "Demo Cirque Aurora", "artist")
    s.add(Booker(user_id=u_dir.id, group_id=grupo.id,
                 position="Director de Entretenimiento del grupo"))
    s.add(Booker(user_id=u_ger.id, company_id=props[0].id,
                 position="Gerente de Entretenimiento"))
    cirque = [a for a in artistas if a.stage_name == "Cirque Aurora"][0]
    cirque.user_id = u_art.id
    s.flush()
    _ = u_admin

    # --- actuaciones -----------------------------------------------------
    # Cada talento trabaja en varias propiedades: eso es lo que hace que la
    # comparativa "aquí contra otras propiedades" tenga con qué compararse.
    inicio = datetime(2026, 2, 2, 21, 0)
    hechas: list[Booking] = []
    futuras = 0
    for a in artistas:
        casas = R.sample(props, R.randint(4, 7))
        if props[0] not in casas:      # el hotel de la demo siempre lo contrató
            casas[0] = props[0]
        # Afinidad con la casa de la demo: unos funcionan mejor aquí que fuera,
        # otros peor. Sin esto todos saldrían iguales y la pantalla no enseñaría
        # para qué sirve la comparativa.
        afinidad = ((sello(a.stage_name + "af") % 5) - 2) * 0.05     # -10% .. +10%
        for c in casas:
            for _n in range(R.randint(3, 5)):
                sh = R.choice(shows[a.id])
                # El salón grande se usa la mitad de las noches en TODAS las
                # propiedades. Si se eligiera al azar entre todos, un hotel con
                # tres salones chicos convocaría siempre menos y la comparativa
                # estaría midiendo el tamaño del salón, no el tirón del talento.
                grandes, chicos = salones[c.id][:1], salones[c.id][1:]
                v = R.choice(grandes * len(chicos) + chicos)
                dia = inicio + timedelta(days=R.randint(0, 190), hours=R.choice([0, 1]))
                if dia > HOY - timedelta(days=2):
                    dia = HOY - timedelta(days=R.randint(3, 60))
                # Llenado: cada talento tiene su propio nivel, con ruido por noche.
                # El "sello" sale de las letras del nombre, no de hash(): hash()
                # de un texto cambia en cada arranque de Python y la demo dejaría
                # de ser la misma de una corrida a otra.
                base_llenado = 0.45 + (sello(a.stage_name) % 45) / 100      # 0.45 .. 0.89
                aqui = afinidad if c.id == props[0].id else 0.0
                llenado = min(1.02, max(0.28, R.gauss(base_llenado + aqui, 0.08)))
                gente = max(20, int(v.capacity * llenado))
                base_ret = 0.68 + (sello(a.stage_name + "r") % 30) / 100     # 0.68 .. 0.97
                ret = min(1.05, max(0.45, R.gauss(base_ret + aqui / 2, 0.05)))
                precio = float(sh.price_hotel or sh.base_price or 20000)
                precio = round(precio * R.uniform(0.9, 1.15), -2)
                b = Booking(
                    show_id=sh.id, venue_id=v.id, company_id=c.id, artist_id=a.id,
                    starts_at=dia, ends_at=dia + timedelta(minutes=sh.duration_minutes or 60),
                    status="completed", event_type="hotel", agreed_price=precio,
                    currency="MXN", commission_pct=15,
                    headcount_start=gente, headcount_end=int(gente * ret),
                    confirmed_at=dia - timedelta(days=R.randint(10, 40)),
                    # notified_at: sin esto el músico no ve la actuación en su
                    # panel (sólo ve lo que el hotel ya le mandó, no borradores).
                    notified_at=dia - timedelta(days=R.randint(10, 40)),
                    invoice_paid=True, payout_paid=True,
                )
                s.add(b)
                hechas.append(b)
        # Un par de fechas por venir, para que la agenda no salga vacía.
        for _n in range(R.randint(1, 3)):
            sh = R.choice(shows[a.id])
            c = R.choice(props)
            v = R.choice(salones[c.id])
            dia = HOY + timedelta(days=R.randint(3, 70), hours=R.choice([8, 9]))
            s.add(Booking(
                show_id=sh.id, venue_id=v.id, company_id=c.id, artist_id=a.id,
                starts_at=dia, ends_at=dia + timedelta(minutes=sh.duration_minutes or 60),
                status=R.choice(["confirmed", "confirmed", "pending"]), event_type="hotel",
                agreed_price=float(sh.price_hotel or 20000), currency="MXN",
                commission_pct=15, invoice_paid=False, payout_paid=False,
                notified_at=HOY - timedelta(days=R.randint(1, 20)),
            ))
            futuras += 1
    s.flush()

    # --- reseñas ---------------------------------------------------------
    # Sólo sobre actuaciones que ya ocurrieron, como en producción: una reseña
    # nace de una actuación concreta y la firma el hotel que la contrató.
    resenas = 0
    for b in hechas:
        if R.random() > 0.55:
            continue
        ret = (b.headcount_end or 0) / (b.headcount_start or 1)
        nota = 5 if ret > 0.9 else 4 if ret > 0.75 else 3
        if R.random() < 0.18:
            nota = max(3, nota - 1)
        firma = R.choice(FIRMAS)
        s.add(Review(
            booking_id=b.id, artist_id=b.artist_id, show_id=b.show_id,
            company_id=b.company_id, rating=nota, comment=R.choice(COMENTARIOS[nota]),
            afluencia="alta" if ret > 0.85 else "media",
            retencion="alta" if ret > 0.85 else "media",
            author_name=firma[0], author_position=firma[1],
            created_at=b.starts_at + timedelta(days=R.randint(1, 6)),
        ))
        resenas += 1

    s.commit()
    print(f"propiedades: {len(props)} (3 en el grupo, {len(SUELTOS)} independientes)")
    print(f"salones: {sum(len(v) for v in salones.values())}")
    print(f"talentos: {len(artistas)}  shows: {sum(len(v) for v in shows.values())}")
    print(f"actuaciones realizadas: {len(hechas)}   por venir: {futuras}")
    print(f"reseñas: {resenas}")
    print(f"usuarios: demo.hotel@showma.mx / demo.director@showma.mx / "
          f"demo.artista@showma.mx / demo.admin@showma.mx  (clave {CLAVE})")


if __name__ == "__main__":
    main()
