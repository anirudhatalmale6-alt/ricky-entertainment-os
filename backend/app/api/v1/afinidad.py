"""Cuestionario de afinidad: guardar respuestas y recomendar shows por salón.

El cálculo vive en app/services/afinidad.py; aquí sólo está el guardado y el
permiso de quién puede tocar qué. Tres fichas distintas:

- La PROPIEDAD contesta lo que no cambia entre sus salas (concepto, estilo,
  público, personalidad, innovación).
- Cada SALÓN elige un mood, que rellena de golpe lo que sí cambia (protagonismo,
  interacción, energía, objetivo), y puede retocarlo a mano.
- Cada SHOW contesta las diez.

Se valida al GUARDAR y no sólo al calcular. Una respuesta que no está en su
lista no puede cruzar contra nada, y si entra a la base se convierte en un show
que nunca aparece recomendado sin que nadie sepa por qué.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import CurrentScope, CurrentUser, DbSession, ensure_company_access
from app.models.artist import Artist
from app.models.company import Company
from app.models.show import Show
from app.models.venue import Venue
from app.services import afinidad as af

router = APIRouter(prefix="/afinidad", tags=["afinidad"])


class RespuestasIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    respuestas: dict[str, object]


class SalonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mood: str | None = None
    respuestas: dict[str, object] | None = None


def _validar(respuestas: dict, permitidas: list[str]) -> dict:
    """Deja sólo preguntas de este nivel y comprueba que las respuestas existan.

    Se descarta en silencio lo que no toca a este nivel (una propiedad mandando
    la P3, por ejemplo) porque el formulario puede mandar de más; lo que NO se
    perdona es una respuesta inventada, porque eso sí es un dato corrupto.
    """
    limpio: dict[str, object] = {}
    for pregunta, valor in (respuestas or {}).items():
        if pregunta not in permitidas:
            continue
        if valor in (None, "", []):
            continue
        try:
            af._indices(pregunta, valor)
        except af.RespuestaInvalida as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail=str(e)) from e
        limpio[pregunta] = valor
    return limpio


async def _show_propio(db: DbSession, scope: CurrentScope, show_id: int) -> Show:
    show = await db.get(Show, show_id)
    if show is None:
        raise HTTPException(status_code=404, detail="Show not found")
    if scope.is_admin:
        return show
    # La productora contesta por los suyos: el perfil lo gestiona ella (David,
    # 02/09), y sería absurdo que pudiera editar la ficha del músico pero no las
    # diez preguntas que deciden si lo recomiendan.
    if scope.artist_ids and show.artist_id in scope.artist_ids:
        return show
    raise HTTPException(status_code=404, detail="Show not found")


@router.get("/cuestionario")
async def cuestionario(user: CurrentUser):
    """Las preguntas, sus opciones y quién contesta cada una.

    Lo sirve el servidor para que el formulario no tenga las opciones copiadas:
    una lista duplicada en el navegador se queda vieja el día que David cambie
    una respuesta, y entonces se guardan textos que no cruzan contra nada.
    """
    return {
        "preguntas": {
            clave: {
                "titulo": titulo,
                "opciones": opciones,
                "multiple": clave in af.MULTIPLES,
                "max": af.MAX_SELECCIONES if clave in af.MULTIPLES else 1,
            }
            for clave, (titulo, opciones, _) in af.PREGUNTAS.items()
        },
        "propiedad": af.PREGUNTAS_PROPIEDAD,
        "salon": af.PREGUNTAS_SALON,
        "moods": af.MOODS,
        "scores": af.NOMBRES_SCORE,
        "suelo": af.SUELO,
    }


@router.get("/propiedad/{company_id}")
async def leer_propiedad(company_id: int, user: CurrentUser, db: DbSession):
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    await ensure_company_access(user, company_id, db)
    return {"company_id": company_id, "name": company.name,
            "respuestas": company.afinidad or {}}


@router.put("/propiedad/{company_id}")
async def guardar_propiedad(company_id: int, payload: RespuestasIn,
                            user: CurrentUser, db: DbSession):
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    await ensure_company_access(user, company_id, db)
    company.afinidad = _validar(payload.respuestas, af.PREGUNTAS_PROPIEDAD)
    await db.commit()
    return {"company_id": company_id, "respuestas": company.afinidad}


@router.get("/salon/{venue_id}")
async def leer_salon(venue_id: int, user: CurrentUser, db: DbSession):
    venue = await db.get(Venue, venue_id)
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")
    await ensure_company_access(user, venue.company_id, db)
    return {
        "venue_id": venue_id, "name": venue.name, "mood": venue.mood,
        "respuestas": venue.afinidad or {},
        # Lo que va a usar el cálculo, ya con el mood aplicado: así el formulario
        # puede enseñar qué quedó puesto sin repetir aquí la lógica de mezcla.
        "efectivas": af.perfil_salon(venue.mood, venue.afinidad),
    }


@router.put("/salon/{venue_id}")
async def guardar_salon(venue_id: int, payload: SalonIn,
                        user: CurrentUser, db: DbSession):
    venue = await db.get(Venue, venue_id)
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")
    await ensure_company_access(user, venue.company_id, db)
    if payload.mood is not None:
        mood = payload.mood.upper().strip()
        if mood and mood not in af.MOODS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Mood desconocido: {payload.mood!r}. "
                       f"Opciones: {', '.join(af.MOODS)}")
        venue.mood = mood or None
    if payload.respuestas is not None:
        venue.afinidad = _validar(payload.respuestas, af.PREGUNTAS_SALON)
    await db.commit()
    return {"venue_id": venue_id, "mood": venue.mood,
            "respuestas": venue.afinidad or {},
            "efectivas": af.perfil_salon(venue.mood, venue.afinidad)}


@router.get("/show/{show_id}")
async def leer_show(show_id: int, scope: CurrentScope, db: DbSession):
    show = await _show_propio(db, scope, show_id)
    return {"show_id": show_id, "show_name": show.show_name,
            "respuestas": show.afinidad or {}}


@router.put("/show/{show_id}")
async def guardar_show(show_id: int, payload: RespuestasIn,
                       scope: CurrentScope, db: DbSession):
    show = await _show_propio(db, scope, show_id)
    show.afinidad = _validar(payload.respuestas, list(af.PREGUNTAS))
    await db.commit()
    return {"show_id": show_id, "respuestas": show.afinidad}


@router.get("/recomendaciones/{venue_id}")
async def recomendaciones(venue_id: int, user: CurrentUser, db: DbSession,
                          limite: int = Query(20, ge=1, le=100)):
    """Los shows ordenados para ESTE salón, con el porqué y los avisos.

    Ordena por la media de los tres scores, pero devuelve los tres por separado:
    un show puede sacar 95 de marca y 25 de experiencia, y ésa es justo la
    información que un promedio único destruiría.

    Los que no han contestado el cuestionario NO se cuelan al final con un cero:
    salen aparte, marcados como incompletos. Un cero diría "no encaja" cuando lo
    que pasa es que nadie ha rellenado la ficha todavía.
    """
    venue = await db.get(Venue, venue_id)
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")
    await ensure_company_access(user, venue.company_id, db)
    company = await db.get(Company, venue.company_id)

    perfil = af.perfil_hotel(
        (company.afinidad if company is not None else None) or {},
        af.perfil_salon(venue.mood, venue.afinidad),
    )
    if not perfil:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ni la propiedad ni el salón han contestado el cuestionario.")

    shows = (await db.execute(
        select(Show, Artist)
        .join(Artist, Artist.id == Show.artist_id)
        .where(Show.is_active.is_(True), Artist.is_active.is_(True))
    )).all()

    listos, incompletos = [], []
    for show, artist in shows:
        fila = {"show_id": show.id, "show_name": show.show_name,
                "artist_id": artist.id, "artist_name": artist.stage_name,
                "category": show.category, "subcategory": show.subcategory}
        if not show.afinidad:
            incompletos.append(fila)
            continue
        resultado = af.puntuar(perfil, show.afinidad)
        notas = [d["score"] for d in resultado.values() if d["score"] is not None]
        if not notas:
            incompletos.append(fila)
            continue
        fila |= {
            "scores": {n: d["score"] for n, d in resultado.items()},
            "cobertura": min(d["cobertura"] for d in resultado.values()),
            "avisos": sorted({p for d in resultado.values() for p in d["avisos"]}),
            "motivos": af.motivos(resultado),
            "media": round(sum(notas) / len(notas), 1),
        }
        listos.append(fila)

    listos.sort(key=lambda f: f["media"], reverse=True)
    return {
        "venue": {"id": venue.id, "name": venue.name, "mood": venue.mood,
                  "company": company.name if company else None},
        "perfil": perfil,
        "recomendaciones": listos[:limite],
        "sin_cuestionario": incompletos,
    }
