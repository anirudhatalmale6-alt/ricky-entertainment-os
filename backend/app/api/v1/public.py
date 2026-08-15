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
from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.models.artist import Artist
from app.models.booking import Booking
from app.models.company import Company
from app.models.enums import BookingStatus
from app.models.review import Review

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
