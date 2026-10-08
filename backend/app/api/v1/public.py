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
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import DbSession
from app.models.artist import Artist
from app.models.booking import Booking
from app.models.company import Company
from app.models.enums import BookingStatus
from app.models.review import Review
from app.core.config import settings
from app.core.storage import UPLOAD_DIR
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


def _viva(url: str | None) -> str | None:
    """La misma direccion si el archivo existe de verdad; None si no.

    En una pantalla de dentro una imagen rota es una molestia; en la tarjeta
    publica es la primera impresion que se lleva un hotel, y ademas es la que
    se pega en WhatsApp. La base guarda rutas que pueden haber quedado
    huerfanas —ya paso en este proyecto con un prefijo /ricky/ de un despliegue
    viejo—, asi que antes de publicar una foto se comprueba que este ahi.

    Solo se revisan las que servimos nosotros. Una direccion externa no se
    puede comprobar sin salir a la red, y eso no se hace al pintar una pagina.
    """
    if not url:
        return None
    if url.startswith("http://") or url.startswith("https://"):
        return url          # externa: no se puede comprobar sin salir a la red
    if "/uploads/" not in url:
        return url
    # Se busca "/uploads/" EN CUALQUIER PARTE, no solo al principio: la base
    # guarda valores con el tramo de la app metido dentro
    # ("/demo/uploads/x.jpg", y en su dia "/ricky/uploads/x.jpg"), asi que
    # comparar contra el principio de la cadena dejaba pasar justo los rotos.
    nombre = url.split("/uploads/", 1)[1].split("?")[0].split("/")[-1]
    if not (UPLOAD_DIR / nombre).is_file():
        return None
    # Y se devuelve la ruta CANONICA, no la guardada: asi un prefijo viejo
    # dentro del dato no puede volver a producir una direccion que no abre.
    return f"{settings.ROOT_PATH}/uploads/{nombre}"


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


async def _resenas_publicas(db: AsyncSession, artist_id: int, limite: int = 8):
    """Las resenas con su hotel y la fecha de la actuacion que las origino.

    Se piden en tres consultas y no con joins para no arrastrar los modelos
    enteros: de la empresa solo se usan nombre y logo.
    """
    filas = list((await db.execute(
        select(Review).where(Review.artist_id == artist_id)
        .order_by(Review.created_at.desc()).limit(limite)
    )).scalars().all())
    if not filas:
        return []

    empresas: dict[int, Company] = {}
    ids = {r.company_id for r in filas if r.company_id}
    if ids:
        for c in (await db.execute(
            select(Company).where(Company.id.in_(ids))
        )).scalars().all():
            empresas[c.id] = c

    fechas: dict[int, object] = {}
    bids = {r.booking_id for r in filas if r.booking_id}
    if bids:
        for bid, inicio in (await db.execute(
            select(Booking.id, Booking.starts_at).where(Booking.id.in_(bids))
        )).all():
            fechas[bid] = inicio

    return [
        (r, empresas.get(r.company_id or 0), fechas.get(r.booking_id))
        for r in filas
    ]


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
        fotos = [f for f in (_viva(im.url) for im in s.images) if f]
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

    # --- Lo que la plataforma puede DEMOSTRAR --------------------------
    # David, 27/08: "instagram es lo que mas estan usando para presentarse,
    # pero no da datos... casi como una tarjeta de pokemon". Esta es la parte
    # que Instagram no puede dar y que el musico no se puede inventar: sale
    # entera de sus actuaciones dentro de SHOWMA.
    #
    # Se reusa `trayectoria.de_artista` TAL CUAL, no una copia. El dia que
    # "cumplida" signifique una cosa en el perfil de dentro y otra en la
    # tarjeta publica, el musico ensena un numero y el hotel ve otro, y ahi se
    # acaba el unico argumento de esto. Sus dos reglas de honestidad viajan
    # con el: cada porcentaje trae su muestra, y por debajo del minimo no se
    # publica porcentaje ninguno (`nuevo`).
    from app.services import distinciones as _dist, trayectoria as _tray

    t = await _tray.de_artista(db, a)
    tray = {
        "desde": t.get("desde"),
        "actuaciones": t.get("actuaciones"),
        "hoteles": t.get("hoteles"),
        "nuevo": t.get("nuevo"),
        "calificacion": t.get("calificacion"),
        "recontratacion": t.get("recontratacion"),
        "cumplimiento": t.get("cumplimiento"),
        "respuesta": t.get("respuesta"),
        "publico": t.get("publico"),
        # El company_id no sale: es un identificador interno y aqui no le sirve
        # a nadie mas que a quien quiera enumerar la cartera de clientes.
        "hoteles_detalle": [
            {**{k: v for k, v in h.items() if k != "company_id"},
             "logo_url": _viva(h.get("logo_url"))}
            for h in (t.get("hoteles_detalle") or [])
        ],
        "distinciones": await _dist.de_artista(db, a.id),
    }

    # --- Los comentarios de los hoteles --------------------------------
    # Va el NOMBRE DEL HOTEL y el CARGO de quien firma, nunca su nombre propio:
    # la persona escribio esa opinion dentro de una plataforma cerrada, no para
    # que su nombre apareciera en una pagina abierta de internet. El cargo da
    # la misma credibilidad sin publicar a nadie.
    resenas = []
    for r, empresa, fecha in await _resenas_publicas(db, a.id):
        resenas.append({
            "estrellas": r.rating,
            "comentario": r.comment,
            "hotel": empresa.name if empresa is not None else None,
            "logo": _viva(empresa.logo_url) if empresa is not None else None,
            "cargo": r.author_position,
            "fecha": fecha.date().isoformat() if fecha else None,
        })

    # La portada: su foto de perfil y, si no tiene, la primera de sus shows.
    # Si no hay ninguna, va None y la tarjeta pinta las iniciales sobre el
    # degradado de su categoria, igual que el catalogo de dentro.
    portada = _viva(a.profile_image_url) or (galeria[0] if galeria else None)

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
        "trayectoria": tray,
        "resenas": resenas,
    }


@router.get("/artist/{slug}")
async def public_artist(slug: str, db: DbSession) -> dict:
    data = await tarjeta_data(db, slug)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Tarjeta no disponible"
        )
    return data


# ---------------------------------------------------------------------------
# PASE DE ACCESO de una actuación: lo que ve el personal de seguridad del hotel
# al escanear el QR. PÚBLICO a propósito — el de la caseta no tiene cuenta en
# SHOWMA, y pedirle una es la forma más rápida de que nadie lo use.
#
# Por eso aquí se enseña lo JUSTO: quién llega, cuántos son, cuándo, en qué
# salón y en qué estado está la actuación. Ni precio, ni comisión, ni teléfono,
# ni correo de nadie. Esta respuesta la puede leer cualquiera a quien le
# reenvíen el mensaje.
# ---------------------------------------------------------------------------

async def pase_data(db: AsyncSession, token: str) -> dict | None:
    from app.models.venue import Venue
    from app.services import pase as pase_svc

    if not token or len(token) < 16:
        return None
    b = (await db.execute(
        select(Booking).where(Booking.pase_token == token))).scalar_one_or_none()
    if b is None:
        return None

    artista = await db.get(Artist, b.artist_id) if b.artist_id else None
    show = await db.get(Show, b.show_id) if b.show_id else None
    venue = await db.get(Venue, b.venue_id) if b.venue_id else None
    empresa = await db.get(Company, b.company_id) if b.company_id else None

    estado = b.status.value if hasattr(b.status, "value") else str(b.status)
    texto, color = pase_svc.ESTADOS.get(estado, (estado, "pend"))
    # Cuántos llegan: lo dice el show, que es donde el proveedor declara los
    # integrantes. Sin dato se dice que no se declaró, no se inventa un 1.
    integrantes = getattr(show, "members", None)

    return {
        "folio": b.folio,
        "quien": (artista.stage_name if artista else None) or "— sin proveedor —",
        "codigo_proveedor": artista.codigo if artista else None,
        "show": show.show_name if show else None,
        "integrantes": int(integrantes) if integrantes else None,
        "cuando": b.starts_at.isoformat() if b.starts_at else None,
        "termina": b.ends_at.isoformat() if b.ends_at else None,
        "hotel": empresa.name if empresa else None,
        "salon": venue.name if venue else None,
        "estado": estado,
        "estado_texto": texto,
        "estado_color": color,
        "puede_pasar": pase_svc.puede_pasar(estado),
        "llegada_at": b.llegada_at.isoformat() if b.llegada_at else None,
        "llegada_por": b.llegada_por,
    }


class LlegadaIn(BaseModel):
    quien: str | None = Field(None, max_length=120)


@router.get("/pase/{token}")
async def pase_publico(token: str, db: DbSession) -> dict:
    data = await pase_data(db, token)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pase no válido")
    return data


@router.post("/pase/{token}/llegada")
async def confirmar_llegada(token: str, payload: LlegadaIn, db: DbSession) -> dict:
    """Seguridad confirma que el grupo llegó.

    Se puede llamar sin cuenta: la protección es el token, que no se adivina.
    Y NO cambia el estado de la actuación ni toca dinero — sólo apunta la hora
    de llegada. Que algo pasó por la puerta no es lo mismo que que la actuación
    se realizó, y mezclarlas haría que entrara a facturación gente que llegó y
    luego no tocó. Lo que confirma que ocurrió sigue siendo la calificación del
    hotel.
    """
    b = (await db.execute(
        select(Booking).where(Booking.pase_token == token))).scalar_one_or_none()
    if b is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pase no válido")
    estado = b.status.value if hasattr(b.status, "value") else str(b.status)
    if estado in ("cancelled",):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Esta actuación está cancelada. No registres la llegada: avisa a quien la contrató.")
    if b.llegada_at is None:          # la primera marca manda; no se pisa
        from app.services import historial

        b.llegada_at = datetime.utcnow()
        b.llegada_por = (payload.quien or "").strip()[:120] or None
        historial.registrar(
            db, b, historial.LLEGADA, "Llegada confirmada en el acceso",
            detalle=(f"La registro {b.llegada_por}" if b.llegada_por else
                     "Sin nombre de quien la registro"),
            actor_nombre=b.llegada_por, actor_rol="seguridad")
        await db.commit()
        await db.refresh(b)
    return {
        "ok": True,
        "llegada_at": b.llegada_at.isoformat() if b.llegada_at else None,
        "llegada_por": b.llegada_por,
    }


# ---------------------------------------------------------------------------
# RESPONDER UNA ACTUACION DESDE EL CORREO (David, 08/10). Publico y sin cuenta:
# la proteccion es el token, que no se adivina.
#
# Abrir el enlace NO acepta nada: solo pinta la pagina. Lo que decide es el
# POST del boton. Es deliberado -ver services/respuesta-: los filtros de correo
# abren los enlaces entrantes para analizarlos, y un GET que aceptara dejaria la
# actuacion comprometida por un antivirus antes de que el musico la leyera.
# ---------------------------------------------------------------------------

class RespuestaIn(BaseModel):
    motivo: str | None = Field(None, max_length=300)


@router.get("/responder/{token}")
async def responder_datos(token: str, db: DbSession) -> dict:
    from app.services import respuesta as resp

    b = await resp.por_token(db, token)
    if b is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Enlace no válido")
    return await resp.datos_para_pantalla(db, b)


@router.post("/responder/{token}/aceptar")
async def responder_aceptar(token: str, db: DbSession, bg: BackgroundTasks) -> dict:
    from app.services import avisos, respuesta as resp

    b = await resp.por_token(db, token)
    if b is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Enlace no válido")
    abierta, motivo = resp.puede_contestar(b)
    if not abierta:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=motivo)

    await resp.aceptar(db, b, origen="correo")
    correos = await _correos_tras_aceptar(db, b)
    await db.commit()
    avisos.despachar(bg, correos)
    return {"ok": True, "estado": "confirmed",
            "mensaje": "Actuación confirmada. Te mandamos tu pase de acceso por correo."}


@router.post("/responder/{token}/rechazar")
async def responder_rechazar(token: str, payload: RespuestaIn, db: DbSession,
                             bg: BackgroundTasks) -> dict:
    from app.models.artist import Artist
    from app.models.company import Company
    from app.models.show import Show
    from app.models.venue import Venue
    from app.services import avisos, respuesta as resp

    b = await resp.por_token(db, token)
    if b is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Enlace no válido")
    abierta, motivo = resp.puede_contestar(b)
    if not abierta:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=motivo)

    await resp.rechazar(db, b, origen="correo", motivo=payload.motivo)

    # Al hotel SI se le avisa de un rechazo: le deja una fecha descubierta y
    # tiene que buscar a otro. (De una aceptacion no se le avisa: la ve en verde.)
    show = await db.get(Show, b.show_id) if b.show_id else None
    venue = await db.get(Venue, b.venue_id) if b.venue_id else None
    artista = await db.get(Artist, b.artist_id) if b.artist_id else None
    empresa = await db.get(Company, b.company_id) if b.company_id else None
    asunto, texto, html = avisos.cancelacion_musico(
        show=(show.show_name if show else None) or "la actuación",
        artista=(artista.stage_name if artista else None) or "El artista",
        venue=(venue.name if venue else "") or "",
        cuando=b.starts_at,
        motivo=(payload.motivo or "El proveedor rechazó la actuación"),
    )
    correos = [avisos.Aviso(to=d, subject=asunto, text=texto, html=html)
               for d in await avisos.correos_hotel(db, b.company_id)]
    await db.commit()
    avisos.despachar(bg, correos)
    return {"ok": True, "estado": "cancelled",
            "mensaje": "Avisamos al hotel de que no puedes. Gracias por contestar."}


async def _correos_tras_aceptar(db, booking) -> list:
    """El pase al proveedor, igual que cuando acepta desde el panel."""
    from app.models.artist import Artist
    from app.models.company import Company
    from app.models.show import Show
    from app.models.venue import Venue
    from app.services import avisos, pase as pase_svc

    artista = await db.get(Artist, booking.artist_id) if booking.artist_id else None
    destino = await avisos.correo_artista(db, artista) if artista else None
    if not destino or not booking.pase_token:
        return []
    show = await db.get(Show, booking.show_id) if booking.show_id else None
    venue = await db.get(Venue, booking.venue_id) if booking.venue_id else None
    empresa = await db.get(Company, booking.company_id) if booking.company_id else None
    url = pase_svc.url_pase(booking.pase_token, settings.public_root)
    asunto, texto, html = avisos.pase_actuacion(
        show=(show.show_name if show else None) or "tu actuación",
        artista=artista.stage_name or "",
        venue=(venue.name if venue else "") or "",
        hotel=(empresa.name if empresa else "") or "",
        cuando=booking.starts_at, folio=booking.folio,
        integrantes=getattr(show, "members", None), url_pase=url)
    return [avisos.Aviso(to=destino, subject=asunto, text=texto, html=html,
                         imagenes={"qrpase": pase_svc.png_qr(url, escala=6)})]
