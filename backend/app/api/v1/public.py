"""Cifras publicas de la plataforma.

GET /public/stats es PUBLICO a proposito: lo consume el aviso de convocatoria
de la portada, que se le muestra a visitantes SIN cuenta.

Devuelve unicamente TOTALES. Nada de esto puede identificar a nadie: ni
nombres, ni correos, ni RFC, ni importes. Si algun dia hace falta otro dato
aqui, se agrega campo por campo y se piensa antes: esta salida la puede leer
cualquiera desde internet.

Los numeros son los reales de la base. No se inflan ni se redondean hacia
arriba: son justo el tipo de dato que un artista le comenta a otro y que un
hotel puede comprobar por dentro.
"""
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession
from app.models.artist import Artist
from app.models.booking import Booking
from app.models.company import Company
from app.models.enums import BookingStatus
from app.models.review import Review
from app.models.show import Show

router = APIRouter(prefix="/public", tags=["public"])

# Una actuacion "gestionada" es la que de verdad llego a existir: la que el
# hotel pidio y el artista acepto, o la que ya se dio. Las canceladas y las
# que siguen pendientes de respuesta no cuentan.
_GESTIONADAS = (BookingStatus.CONFIRMED, BookingStatus.COMPLETED)


@router.get("/stats")
async def public_stats(db: DbSession) -> dict:
    artistas = await db.scalar(select(func.count()).select_from(Artist))
    hoteles = await db.scalar(select(func.count()).select_from(Company))
    actuaciones = await db.scalar(
        select(func.count()).select_from(Booking).where(Booking.status.in_(_GESTIONADAS))
    )
    total_resenas = await db.scalar(select(func.count()).select_from(Review))
    promedio = await db.scalar(select(func.avg(Review.rating)))

    return {
        "artistas": int(artistas or 0),
        "hoteles": int(hoteles or 0),
        "actuaciones": int(actuaciones or 0),
        "resenas": int(total_resenas or 0),
        # Sin reseñas todavia no hay promedio que enseñar: va nulo y el aviso
        # esconde el dato. Un 0.0 se leeria como "los califican pesimo".
        "calificacion": round(float(promedio), 1) if promedio is not None else None,
    }


# ---------------------------------------------------------------------------
# TARJETA DE PRESENTACION del proveedor: el perfil visto desde FUERA, sin
# cuenta y sin sesion. David, 27/08: "convertir/usar el perfil de los
# musicos/shows como una especie de tarjeta de presentacion que se vea externa
# a la plataforma".
#
# Regla de esta salida, y no se negocia: se arma campo por campo con una LISTA
# BLANCA. Nunca se serializa el modelo Artist, que lleva dentro RFC, CLABE,
# cuenta bancaria, razon social, fecha de nacimiento, telefono y correo. Un
# `ArtistOut` aqui seria una fuga de datos fiscales y personales a internet
# abierto, y una que nadie notaria hasta que fuera tarde.
#
# TAMPOCO van los precios. Ni base_price ni ninguna de las siete tarifas ni los
# extras. La tarjeta es para ensenar el show, no para cotizarlo: el precio se
# habla dentro de SHOWMA, que es de lo que vive la plataforma. Lo mismo con el
# telefono y el correo del artista: si la tarjeta los publica, el hotel llama
# directo, y entonces SHOWMA pago la fiesta de otro.
# ---------------------------------------------------------------------------


def _lista(v) -> list:
    """Las columnas JSON pueden traer None en filas viejas."""
    return [x for x in (v or []) if x]


def _youtube(social_links) -> str | None:
    """Del bloque de redes sale UNICAMENTE YouTube, igual que en el perfil de
    dentro. El video es la herramienta de venta; Instagram y la web propia son
    la puerta de salida de la plataforma."""
    v = (social_links or {}).get("youtube")
    if not v:
        return None
    v = str(v).strip()
    if v.startswith("http://") or v.startswith("https://"):
        return v
    return "https://youtube.com/" + v.lstrip("@")


async def tarjeta_data(db: AsyncSession, slug: str) -> dict | None:
    """Los datos publicos de un proveedor, o None si no hay tarjeta que ensenar.

    Devuelve None -y por tanto 404- en tres casos distintos que desde fuera se
    ven iguales a proposito: no existe el slug, existe pero la tarjeta esta
    apagada, o el perfil esta dado de baja. Distinguirlos le diria a un
    curioso quien esta dado de alta sin tarjeta.
    """
    res = await db.execute(
        select(Artist)
        .options(selectinload(Artist.shows).selectinload(Show.images))
        .where(func.lower(Artist.public_slug) == slug.strip().lower())
    )
    a = res.scalar_one_or_none()
    if a is None or not a.is_public or not a.is_active:
        return None

    shows = []
    galeria: list[str] = []
    for s in sorted(a.shows, key=lambda s: s.show_name or ""):
        if not s.is_active:
            continue
        fotos = [im.url for im in s.images if im.url]
        galeria.extend(fotos)
        shows.append({
            "nombre": s.show_name,
            "categoria": s.category,
            "subcategoria": s.subcategory,
            "generos": _lista(s.genres),
            "descripcion": s.description,
            "idiomas": _lista(s.show_languages),
            "integrantes": s.members,
            "duracion_min": s.duration_minutes,
            "espacio": s.space_required,
            "incluye": _lista(s.equipment_included),
            "video": s.video_url,
            "fotos": fotos,
        })

    # La portada: su foto de perfil y, si no tiene, la primera de sus shows.
    # Si no hay ninguna, va None y la tarjeta pinta las iniciales sobre el
    # degradado de su categoria, igual que el catalogo de dentro.
    portada = a.profile_image_url or (galeria[0] if galeria else None)

    return {
        "slug": a.public_slug,
        "nombre": a.stage_name,
        "tipo": a.artist_type,
        "bio": a.bio,
        "portada": portada,
        "ciudad": a.base_city or a.city,
        "region": a.region,
        "experiencia": a.years_experience,
        "idiomas": _lista(a.languages_spoken),
        "viaja": bool(a.available_to_travel),
        "verificado": bool(a.is_verified),
        "partner": bool(a.is_partner),
        "youtube": _youtube(a.social_links),
        "categoria": shows[0]["categoria"] if shows else None,
        "shows": shows,
        "galeria": galeria[:12],
    }


@router.get("/artist/{slug}")
async def public_artist(slug: str, db: DbSession) -> dict:
    data = await tarjeta_data(db, slug)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tarjeta no disponible"
        )
    return data
