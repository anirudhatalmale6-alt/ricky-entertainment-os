"""Self-service endpoints: what the logged-in artist can do to their OWN profile.

The catalogue endpoints in artists.py / shows.py are gated behind
`artist.manage` (an admin/agency permission). An artist managing *their own*
profile shouldn't need that: identity comes from the session (scope.artist_id),
and every write is confined to the profile that belongs to the caller. This is
what powers the "Mi Perfil" screen where a musician edits their tarifas,
descripciones and gestiona sus publicaciones (shows).
"""
import uuid
from datetime import date as date_cls, datetime, timedelta

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import delete as sa_delete, select, update
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentScope, DbSession
from app.core.config import settings
from app.core.storage import ensure_upload_dir
from app.models.artist import Artist
from app.models.artist_client_rate import ArtistClientRate
from app.models.blocked_date import ArtistBlockedDate
from app.models.booking import Booking
from app.models.company import Company
from app.models.conversation import Conversation, Message
from app.models.enums import BookingStatus
from app.models.property_group import PropertyGroup
from app.models.tax_figure import TaxFigure
from app.models.cfdi import Cfdi
from app.models.venue import Venue
from app.models.user import Role, User
from app.core import security
from app.services.facturama import FacturamaError, get_facturama
from app.services import afinidad as af
from app.services import facturacion, mailer, passwords, periodos, rfc as rfc_svc
from app.models.contract import (
    ARTIST_CONTRACT_SLUG,
    ContractAcceptance,
    ContractTemplate,
)
from app.models.notification import ArtistNotification
from app.models.media import ArtistDocument, ShowImage
from app.models.seasonal_rate import ShowSeasonalRate
from app.models.show import Show
from app.schemas.artist import ArtistOut, ArtistUpdate
from app.schemas.show import ShowCreate, ShowOut, ShowUpdate


class BlockedDateIn(BaseModel):
    date: date_cls
    reason: str | None = None

router = APIRouter(prefix="/me", tags=["me"])

# Images are resized/compressed on the client before upload, so these are small.
_ALLOWED_IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_MAX_IMAGE_BYTES = 6 * 1024 * 1024

_ARTIST_RELS = (
    selectinload(Artist.shows).selectinload(Show.images),
    selectinload(Artist.shows).selectinload(Show.seasonal_rates),
    selectinload(Artist.documents),
)
_SHOW_RELS = (
    selectinload(Show.images),
    selectinload(Show.seasonal_rates),
)

# Fields an artist may NOT flip on themselves - trust/verification is set by the
# platform, never self-granted.
# Campos que el proveedor NO se puede poner a sí mismo por mucho que viajen en
# el mismo formulario. Los tres los otorga SHOWMA, no el que llena la ficha:
#   is_verified    - el sello de verificado.
#   is_productora  - poder dar de alta musicos, o sea CREAR cuentas y MANDAR
#                    correos desde el dominio de SHOWMA.
#   is_partner /   - el plan de pago que abre Market Intelligence, Tendencias y
#   partner_...      Noticias. Sin esto, cualquiera se regala el add-on con un
#                    PATCH a mano y deja de pagarlo.
_PROTECTED = {"is_verified", "is_productora", "is_partner", "partner_monthly_fee"}


async def _require_artist(scope: CurrentScope) -> int:
    if scope.artist_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta cuenta no tiene un perfil de artista asociado",
        )
    return scope.artist_id


async def _require_cobra(scope: CurrentScope) -> int:
    """El artist_id de quien factura por su cuenta.

    Un músico que trabaja dentro de una productora no cobra por SHOWMA: la
    plataforma le factura y le paga a la EMPRESA, y ellos se liquidan por fuera
    (David, 28/08). Así que todo lo que huele a dinero -pagos, CFDI, CSD,
    tarifas por cliente- se le cierra AQUÍ, en el servidor, y no sólo
    escondiendo el botón: una pantalla oculta se sigue pudiendo llamar a mano.
    """
    artist_id = await _require_artist(scope)
    if scope.parent_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tus pagos los lleva la empresa a la que perteneces, no SHOWMA.",
        )
    return artist_id


async def _require_ficha_propia(scope: CurrentScope) -> int:
    """El artist_id de quien manda sobre su PROPIA ficha.

    La cuenta del músico de una productora existe para una sola cosa: bloquear
    fechas y consultar sus actuaciones, para que SHOWMA no le confirme un día que
    él ya tiene comprometido por fuera. La ficha la gestiona, la ve y la cobra la
    empresa (David, 02/09).

    Se cierra aquí y no sólo quitando el botón: si dos manos pudieran editar la
    misma ficha, la empresa que armó el catálogo de 200 perfiles no tendría forma
    de saber por qué uno cambió de nombre o de foto un martes.
    """
    artist_id = await _require_artist(scope)
    if scope.parent_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tu ficha la gestiona la empresa a la que perteneces. "
                   "Tu cuenta es para bloquear fechas y ver tus actuaciones.",
        )
    return artist_id


async def _load_artist(db: DbSession, artist_id: int) -> Artist:
    res = await db.execute(
        select(Artist).options(*_ARTIST_RELS).where(Artist.id == artist_id)
    )
    artist = res.scalar_one_or_none()
    if artist is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artist not found")
    return artist


async def _load_show(db: DbSession, show_id: int) -> Show:
    res = await db.execute(select(Show).options(*_SHOW_RELS).where(Show.id == show_id))
    show = res.scalar_one_or_none()
    if show is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Show not found")
    return show


async def _own_show_or_404(db: DbSession, artist_id: int, show_id: int) -> Show:
    show = await _load_show(db, show_id)
    if show.artist_id != artist_id:
        # Don't leak that the show exists under someone else.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Show not found")
    return show


# --- Profile --------------------------------------------------------------

# Lo que es "facturación" en una ficha. El músico que trabaja dentro de una
# productora no lleva nada de esto: SHOWMA le factura y le paga a la EMPRESA, y
# la empresa liquida a los suyos fuera de la plataforma (David, 28/08). Sus
# datos fiscales son asunto entre ellos dos, no de aquí.
_FISCALES = (
    "rfc", "cfdi_use", "tax_regime", "legal_name", "fiscal_postal_code",
    "bank_name", "bank_account", "bank_account_holder", "bank_clabe",
)


def _sin_facturacion(artist: Artist) -> ArtistOut:
    """La ficha tal cual, y vacía de datos fiscales si cuelga de una productora.

    Se vacía sobre el ArtistOut ya construido y NO sobre el objeto de la base:
    tocarle los campos al objeto vivo dejaría a SQLAlchemy con el borrado
    pendiente, y el primer commit que pasara por ahí guardaría los blancos de
    verdad. Esto esconde un dato; no lo borra.
    """
    out = ArtistOut.model_validate(artist)
    if artist.parent_id:
        return out.model_copy(update={k: None for k in _FISCALES})
    return out


async def _ficha_out(db: DbSession, artist: Artist) -> ArtistOut:
    """La ficha para la pantalla: sin facturación ajena y con el nombre de la
    productora resuelto, para poder decirle al músico a quién pedirle un cambio."""
    out = _sin_facturacion(artist)
    if artist.parent_id:
        madre = await db.get(Artist, artist.parent_id)
        if madre is not None:
            return out.model_copy(update={"parent_name": madre.stage_name})
    return out


@router.get("/artist", response_model=ArtistOut)
async def get_my_profile(scope: CurrentScope, db: DbSession):
    return await _ficha_out(db, await _load_artist(db, await _require_artist(scope)))


def _aplicar_ficha(artist: Artist, payload: ArtistUpdate) -> None:
    """Vuelca el formulario sobre la ficha, quitando lo que no se puede escribir.

    Lo comparten el artista que edita la suya y la productora que edita la de uno
    de los suyos, a propósito: si cada uno filtrara por su lado, el día que se
    agregue un campo delicado habría que acordarse de las dos listas.
    """
    data = payload.model_dump(exclude_unset=True)
    for field in _PROTECTED:
        data.pop(field, None)
    # Esconder la sección en la pantalla no basta: en la ficha de un músico de
    # productora tampoco se ESCRIBEN datos fiscales, ni por él ni por la empresa.
    # Quien cobra es la empresa con SU RFC; un RFC aquí sería un dato que nadie
    # sabría de dónde salió y que no le corresponde cobrar.
    if artist.parent_id:
        for field in _FISCALES:
            data.pop(field, None)
    for field, value in data.items():
        setattr(artist, field, value)


@router.patch("/artist", response_model=ArtistOut)
async def update_my_profile(payload: ArtistUpdate, scope: CurrentScope, db: DbSession):
    artist_id = await _require_ficha_propia(scope)
    artist = await _load_artist(db, artist_id)
    _aplicar_ficha(artist, payload)
    await db.commit()
    return await _ficha_out(db, await _load_artist(db, artist_id))


# --- Facturación / pagos del artista (desglose fiscal) --------------------

# Comisión SHOWMA por defecto (Platform Services) si la figura no la define.
_DEFAULT_COMMISSION_PCT = 3.7
_MES_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
           "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


@router.get("/payouts")
async def my_payouts(scope: CurrentScope, db: DbSession):
    """Facturación del artista con el desglose fiscal completo, siguiendo el
    modelo que definió David: los honorarios contratados menos la comisión SHOWMA
    dan la base para emitir el CFDI; sobre esa base se calcula el IVA trasladado y
    se restan las retenciones de IVA e ISR para llegar al total a recibir. Se
    agrupa por hotel y mes, igual que la facturación del hotel. Los porcentajes
    salen de la figura fiscal del talento (catálogo Impuestos)."""
    artist_id = await _require_cobra(scope)
    artist = await db.get(Artist, artist_id)

    # Figura fiscal del talento (o la predeterminada del catálogo).
    figuras = (await db.execute(select(TaxFigure))).scalars().all()
    by_id = {f.id: f for f in figuras}
    default_fig = next((f for f in figuras if f.is_default), (figuras[0] if figuras else None))
    figura = by_id.get(artist.tax_figure_id) if artist and artist.tax_figure_id else default_fig

    com_pct = float(getattr(figura, "commission_pct", 0) or 0) if figura else 0.0
    if not com_pct:
        com_pct = _DEFAULT_COMMISSION_PCT
    iva_pct = (float(figura.iva_traslado_pct) if figura and figura.iva_traslado_pct is not None else 16.0)
    riva_pct = float(getattr(figura, "iva_ret_pct", 0) or 0) if figura else 0.0
    risr_pct = float(getattr(figura, "isr_ret_pct", 0) or 0) if figura else 0.0

    # Actuaciones facturables: confirmadas o realizadas (dinero comprometido),
    # igual que la facturación del hotel. Los borradores (pending) no cuentan.
    stmt = (
        select(Booking)
        .where(
            Booking.artist_id == artist_id,
            Booking.status.in_((BookingStatus.CONFIRMED, BookingStatus.COMPLETED)),
        )
        .order_by(Booking.starts_at)
    )
    bookings = list((await db.execute(stmt)).scalars().all())
    cids = {b.company_id for b in bookings if b.company_id}
    vids = {b.venue_id for b in bookings if b.venue_id}
    sids = {b.show_id for b in bookings if b.show_id}
    companies = {c.id: c for c in (
        (await db.execute(select(Company).where(Company.id.in_(cids)))).scalars().all() if cids else []
    )}
    venues = {v.id: v for v in (
        (await db.execute(select(Venue).where(Venue.id.in_(vids)))).scalars().all() if vids else []
    )}
    shows = {s.id: s for s in (
        (await db.execute(select(Show).where(Show.id.in_(sids)))).scalars().all() if sids else []
    )}

    # Agrupa por hotel + QUINCENA (David, 2026-08-12): un recibo por periodo, no
    # por mes, para que cuadre con las fechas de corte y de depósito.
    groups: dict[str, dict] = {}
    for b in bookings:
        dt = b.starts_at
        per = periodos.key_for(dt)
        if per is None:
            continue
        key = f"{b.company_id or 0}|{per}"
        comp = companies.get(b.company_id)
        g = groups.setdefault(key, {
            "company_id": b.company_id,
            "company": comp.name if comp else "—",
            "period": per,
            "ym": per[:7],
            "rows": [],
        })
        g["rows"].append(b)

    today = datetime.utcnow()
    invoices = []
    for g in groups.values():
        rows = g["rows"]
        honorarios = round(sum(float(b.agreed_price or 0) for b in rows), 2)
        comision = round(honorarios * com_pct / 100.0, 2)
        base_cfdi = round(honorarios - comision, 2)
        iva = round(base_cfdi * iva_pct / 100.0, 2)
        subtotal_iva = round(base_cfdi + iva, 2)
        ret_iva = round(base_cfdi * riva_pct / 100.0, 2)
        ret_isr = round(base_cfdi * risr_pct / 100.0, 2)
        total_recibir = round(subtotal_iva - ret_iva - ret_isr, 2)

        per = g["period"]
        corte = periodos.cutoff(per)
        deposito = periodos.payment_date(per)
        issue = datetime.combine(corte, datetime.min.time())
        due = datetime.combine(deposito, datetime.min.time())
        cerrado = periodos.is_closed(per, today.date())
        all_paid = bool(rows) and all(getattr(b, "payout_paid", False) for b in rows)
        # "Pagada" sólo si el músico la marcó como cobrada. Antes bastaba con que
        # las actuaciones estuvieran realizadas, lo que daba por cobrado dinero
        # que todavía no se había depositado.
        if all_paid:
            status_s = "paid"
        elif not cerrado:
            status_s = "open"          # la quincena sigue abierta, aún suma
        elif due < today:
            status_s = "overdue"
        else:
            status_s = "sent"

        invoices.append({
            "company_id": g["company_id"], "company": g["company"], "ym": g["ym"],
            "period_key": per,
            "period": periodos.short_label(per),
            "period_label": periodos.label(per),
            "cutoff": corte.strftime("%d/%m/%Y"),
            "payment_date": deposito.strftime("%d/%m/%Y"),
            "closed": cerrado,
            "issue": issue.strftime("%d/%m/%Y"),
            "due": due.strftime("%d/%m/%Y"),
            "status": status_s,
            "honorarios": honorarios,
            "com_pct": round(com_pct, 4), "comision": comision,
            "base_cfdi": base_cfdi,
            "iva_pct": round(iva_pct, 4), "iva": iva,
            "subtotal_iva": subtotal_iva,
            "riva_pct": round(riva_pct, 4), "ret_iva": ret_iva,
            "risr_pct": round(risr_pct, 4), "ret_isr": ret_isr,
            "total_recibir": total_recibir,
            "rows": [{
                "fecha": b.starts_at.isoformat() if b.starts_at else None,
                "show": (shows.get(b.show_id).show_name if shows.get(b.show_id) else None),
                "venue": (venues.get(b.venue_id).name if venues.get(b.venue_id) else None),
                "importe": float(b.agreed_price or 0),
            } for b in rows],
        })

    invoices.sort(key=lambda x: x["period_key"], reverse=True)
    for i, inv in enumerate(invoices):
        inv["no"] = f"INV-{inv['period_key'].replace('-', '')}-{i + 1:03d}"

    return {
        "figura": figura.name if figura else None,
        "isr_variable": bool(getattr(figura, "isr_variable", False)) if figura else False,
        "items": invoices,
    }


class PayoutMarkIn(BaseModel):
    company_id: int
    # Quincena ("2026-08-Q1"). Se sigue aceptando "YYYY-MM" de la versión por
    # meses: en ese caso se marcan las dos quincenas de ese mes.
    period: str | None = None
    ym: str | None = None
    paid: bool = True


@router.post("/payouts/mark")
async def mark_payout(payload: PayoutMarkIn, scope: CurrentScope, db: DbSession):
    """El artista marca su recibo (hotel + mes) como cobrado o revierte el marcado:
    pone payout_paid en sus actuaciones de ese hotel y periodo."""
    artist_id = await _require_cobra(scope)
    rows = (
        await db.execute(
            select(Booking).where(
                Booking.artist_id == artist_id,
                Booking.company_id == payload.company_id,
                Booking.status.in_((BookingStatus.CONFIRMED, BookingStatus.COMPLETED)),
            )
        )
    ).scalars().all()
    objetivo = (payload.period or payload.ym or "").strip()
    if not objetivo:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Indica la quincena a marcar.")
    por_mes = len(objetivo) == 7          # "YYYY-MM" -> el mes completo
    n = 0
    for b in rows:
        dt = b.starts_at
        if dt is None:
            continue
        per = periodos.key_for(dt)
        if (per[:7] if por_mes else per) == objetivo:
            b.payout_paid = payload.paid
            n += 1
    await db.commit()
    return {"updated": n, "paid": payload.paid}


# --- Aviso al hotel: "voy en camino" / "llegué" (estilo Uber Eats) ----------

class NotifyStatusIn(BaseModel):
    status: str   # 'on_way' | 'arrived'


@router.post("/bookings/{booking_id}/notify-status")
async def notify_status(booking_id: int, payload: NotifyStatusIn, scope: CurrentScope, db: DbSession):
    """El artista avisa al hotel, con un clic, que va en camino o que ya llegó a
    la actuación (solo mensaje al chat, sin rastreo). Busca o crea la conversación
    con el hotel de esa actuación y publica el aviso."""
    artist_id = await _require_artist(scope)
    booking = await db.get(Booking, booking_id)
    if booking is None or booking.artist_id != artist_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Actuación no encontrada")
    if booking.company_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Esta actuación no tiene un hotel asociado")
    conv = (
        await db.execute(
            select(Conversation).where(
                Conversation.artist_id == artist_id,
                Conversation.company_id == booking.company_id,
                Conversation.request_id.is_(None),
            ).order_by(Conversation.id).limit(1)
        )
    ).scalar_one_or_none()
    if conv is None:
        conv = Conversation(artist_id=artist_id, company_id=booking.company_id, booking_id=booking_id)
        db.add(conv)
        await db.flush()
    dt = booking.starts_at
    hhmm = dt.strftime("%H:%M") if dt else ""
    if payload.status == "on_way":
        body = "🚗 Voy en camino a la actuación" + (f" de las {hhmm}." if hhmm else ".")
    elif payload.status == "arrived":
        body = "📍 Llegué al lugar."
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Estado no válido")
    db.add(Message(conversation_id=conv.id, sender_role="artist", body=body))
    await db.commit()
    return {"ok": True, "conversation_id": conv.id, "message": body}


# --- Media upload ---------------------------------------------------------

@router.post("/artist/upload-image")
async def upload_image(scope: CurrentScope, file: UploadFile = File(...)):
    """Store a show photo and return its URL.

    The image is already resized to ~1600px JPEG on the client, so here we only
    validate the type/size and write the bytes. The returned URL includes the
    app's ROOT_PATH so it can be used directly as an <img src> (same origin).
    """
    await _require_artist(scope)
    ext = _ALLOWED_IMAGE_TYPES.get((file.content_type or "").lower())
    if ext is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Formato no admitido. Usa JPG, PNG o WEBP.",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Archivo vacío.")
    if len(data) > _MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="La imagen es muy grande (máximo 6 MB).",
        )
    name = f"{scope.artist_id}_{uuid.uuid4().hex}.{ext}"
    (ensure_upload_dir() / name).write_bytes(data)
    return {"url": f"{settings.ROOT_PATH}/uploads/{name}"}


# --- Legal documents ------------------------------------------------------
# Tipos de documento admitidos (coincide con el registro de artista y /MASTER).
_DOC_TYPES = {
    "identificacion", "comprobante_domicilio", "constancia_sat", "contrato",
    "rider_tecnico", "rider_hospitalidad", "press_kit", "comprobante_bancario", "otro",
}
_ALLOWED_DOC_TYPES = {
    "application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png", "image/webp": "webp",
}
_MAX_DOC_BYTES = 10 * 1024 * 1024


def _doc_out(d: ArtistDocument) -> dict:
    return {"id": d.id, "doc_type": d.doc_type, "url": d.url, "filename": d.filename}


@router.get("/artist/documents")
async def list_my_documents(scope: CurrentScope, db: DbSession):
    """Los documentos legales que el artista ya subió."""
    artist_id = await _require_artist(scope)
    res = await db.execute(
        select(ArtistDocument).where(ArtistDocument.artist_id == artist_id)
    )
    return [_doc_out(d) for d in res.scalars().all()]


@router.post("/artist/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    scope: CurrentScope,
    db: DbSession,
    file: UploadFile = File(...),
    doc_type: str = Form(...),
):
    """Sube (o reemplaza) un documento legal del artista.

    Cerrado al músico de una productora: identificación, constancia del SAT y
    contrato son de quien tiene la relación con SHOWMA, y esa es la empresa.

    Un solo archivo por tipo: si ya existe uno de ese `doc_type` se reemplaza,
    para que el registro y /MASTER siempre muestren el vigente.
    """
    artist_id = await _require_ficha_propia(scope)
    if doc_type not in _DOC_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tipo de documento no válido.")
    ext = _ALLOWED_DOC_TYPES.get((file.content_type or "").lower())
    if ext is None:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Formato no admitido. Usa PDF, JPG, PNG o WEBP.",
        )
    data = await file.read()
    if not data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Archivo vacío.")
    if len(data) > _MAX_DOC_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="El documento es muy grande (máximo 10 MB).",
        )
    name = f"doc_{artist_id}_{doc_type}_{uuid.uuid4().hex}.{ext}"
    (ensure_upload_dir() / name).write_bytes(data)
    url = f"{settings.ROOT_PATH}/uploads/{name}"
    filename = (file.filename or f"{doc_type}.{ext}")[:255]

    res = await db.execute(
        select(ArtistDocument).where(
            ArtistDocument.artist_id == artist_id,
            ArtistDocument.doc_type == doc_type,
        )
    )
    doc = res.scalar_one_or_none()
    if doc is None:
        doc = ArtistDocument(artist_id=artist_id, doc_type=doc_type, url=url, filename=filename)
        db.add(doc)
    else:
        doc.url = url
        doc.filename = filename
    await db.commit()
    await db.refresh(doc)
    return _doc_out(doc)


# --- Facturación electrónica (CFDI) · datos fiscales + CSD -----------------
# El músico llena sus datos fiscales UNA vez y sube su CSD (.cer + .key +
# contraseña). Con eso, SHOWMA timbra a su nombre automáticamente en cada
# actuación — sin trabajo manual por factura (requisito de David).

# Régimenes fiscales SAT más comunes para talento (persona física) y hoteles.
# El frontend los usa como catálogo del selector.
_SAT_REGIMES = [
    {"code": "612", "label": "Persona Física · Actividad Empresarial y Profesional"},
    {"code": "626", "label": "Persona Física · RESICO"},
    {"code": "621", "label": "Persona Física · Incorporación Fiscal"},
    {"code": "605", "label": "Persona Física · Sueldos y Salarios"},
    {"code": "606", "label": "Persona Física · Arrendamiento"},
    {"code": "601", "label": "Persona Moral · Régimen General de Ley"},
    {"code": "603", "label": "Persona Moral · Con Fines no Lucrativos"},
    {"code": "620", "label": "Persona Moral · Sociedades Cooperativas de Producción"},
]
_SAT_CFDI_USES = [
    {"code": "G03", "label": "G03 · Gastos en general"},
    {"code": "G01", "label": "G01 · Adquisición de mercancías"},
    {"code": "P01", "label": "P01 · Por definir"},
    {"code": "S01", "label": "S01 · Sin efectos fiscales"},
]

# El .cer del SAT es DER binario; el .key es la llave privada. Aceptamos por
# extensión (los navegadores no siempre mandan un content-type útil para ellos).
_MAX_CSD_BYTES = 512 * 1024


def _fiscal_out(a: Artist) -> dict:
    ready = bool(
        (a.csd_status == "active") and a.rfc and a.tax_regime and a.fiscal_postal_code
    )
    return {
        "rfc": a.rfc,
        "legal_name": a.legal_name,
        "tax_regime": a.tax_regime,
        "cfdi_use": a.cfdi_use,
        "fiscal_postal_code": a.fiscal_postal_code,
        "csd_status": a.csd_status or "none",
        "csd_uploaded_at": a.csd_uploaded_at.isoformat() if a.csd_uploaded_at else None,
        "csd_expires_at": a.csd_expires_at.isoformat() if a.csd_expires_at else None,
        # Aviso (no bloqueo) cuando el dígito verificador no cuadra: el timbrado
        # fallaría más adelante y es mejor verlo aquí.
        "rfc_aviso": rfc_svc.check(a.rfc)["mensaje"],
        "ready": ready,
        "regimes": _SAT_REGIMES,
        "cfdi_uses": _SAT_CFDI_USES,
    }


class FiscalDataIn(BaseModel):
    rfc: str | None = None
    legal_name: str | None = None
    tax_regime: str | None = None        # código SAT (p.ej. "612")
    cfdi_use: str | None = None
    fiscal_postal_code: str | None = None


@router.get("/fiscal")
async def get_my_fiscal(scope: CurrentScope, db: DbSession):
    """Datos fiscales del músico + estado de su CSD para facturación."""
    artist_id = await _require_cobra(scope)
    artist = await _load_artist(db, artist_id)
    return _fiscal_out(artist)


@router.post("/fiscal")
async def save_my_fiscal(payload: FiscalDataIn, scope: CurrentScope, db: DbSession):
    """Guarda los datos fiscales (RFC, razón social, régimen, CP, uso CFDI)."""
    artist_id = await _require_cobra(scope)
    artist = await _load_artist(db, artist_id)
    if payload.rfc is not None:
        chk = rfc_svc.check(payload.rfc)
        # Sólo se rechaza lo que con seguridad está mal escrito. Si lo que falla
        # es el dígito verificador se guarda igual y el aviso viaja de vuelta,
        # porque el SAT tiene emitidos unos cuantos RFC que no cumplen el cálculo.
        if not chk["ok"]:
            raise HTTPException(status_code=422, detail=chk["mensaje"])
        artist.rfc = chk["rfc"] or None
    if payload.legal_name is not None:
        artist.legal_name = payload.legal_name.strip() or None
    if payload.tax_regime is not None:
        artist.tax_regime = payload.tax_regime.strip() or None
    if payload.cfdi_use is not None:
        artist.cfdi_use = payload.cfdi_use.strip() or None
    if payload.fiscal_postal_code is not None:
        artist.fiscal_postal_code = payload.fiscal_postal_code.strip() or None
    await db.commit()
    await db.refresh(artist)
    return _fiscal_out(artist)


@router.post("/fiscal/csd")
async def upload_csd(
    scope: CurrentScope,
    db: DbSession,
    cer: UploadFile = File(...),
    key: UploadFile = File(...),
    password: str = Form(...),
    rfc: str = Form(...),
):
    """Sube y VALIDA el CSD del músico contra Facturama (una sola vez).

    Facturama verifica que el certificado corresponda al RFC y que la contraseña
    de la llave sea correcta; si algo no cuadra, devuelve el motivo y no se
    marca como listo. En éxito, el RFC queda habilitado para timbrar a su nombre.
    """
    artist_id = await _require_cobra(scope)
    artist = await _load_artist(db, artist_id)

    rfc = (rfc or "").strip().upper()
    if not rfc:
        raise HTTPException(status_code=400, detail="Indica tu RFC.")
    if not (password or "").strip():
        raise HTTPException(status_code=400, detail="Indica la contraseña de tu llave (.key).")

    cer_bytes = await cer.read()
    key_bytes = await key.read()
    if not cer_bytes or not key_bytes:
        raise HTTPException(status_code=400, detail="Faltan archivos: sube tu .cer y tu .key.")
    if len(cer_bytes) > _MAX_CSD_BYTES or len(key_bytes) > _MAX_CSD_BYTES:
        raise HTTPException(status_code=413, detail="Los archivos del CSD son demasiado grandes.")

    client = get_facturama()
    try:
        result = await client.upload_csd(rfc, cer_bytes, key_bytes, password)
    except FacturamaError as exc:
        # No pudo validarse: marcamos el estado como error y devolvemos el motivo.
        artist.csd_status = "error"
        await db.commit()
        raise HTTPException(status_code=422, detail=exc.message)

    artist.rfc = rfc
    artist.csd_status = "active"
    artist.csd_uploaded_at = date_cls.today()
    exp = (result or {}).get("CsdExpirationDate") if isinstance(result, dict) else None
    if not exp:
        # Un reemplazo (PUT) no siempre trae la vigencia; la leemos del CSD.
        try:
            csd = await client.get_csd(rfc)
            exp = (csd or {}).get("CsdExpirationDate") if isinstance(csd, dict) else None
        except FacturamaError:
            exp = None
    if exp:
        try:
            artist.csd_expires_at = datetime.fromisoformat(exp.replace("Z", "")).date()
        except (ValueError, AttributeError):
            artist.csd_expires_at = None
    await db.commit()
    await db.refresh(artist)
    return _fiscal_out(artist)


# --- CFDIs emitidos del músico --------------------------------------------

def _cfdi_out(c: Cfdi) -> dict:
    return {
        "id": c.id,
        "booking_id": c.booking_id,
        "status": c.status,
        "uuid": c.uuid,
        "serie": c.serie,
        "folio": c.folio,
        "issuer_rfc": c.issuer_rfc,
        "receiver_rfc": c.receiver_rfc,
        "subtotal": float(c.subtotal) if c.subtotal is not None else None,
        "total": float(c.total) if c.total is not None else None,
        "stamped_at": c.stamped_at.isoformat() if c.stamped_at else None,
        "error": c.error,
    }


@router.get("/cfdis")
async def my_cfdis(scope: CurrentScope, db: DbSession):
    """Lista los CFDI emitidos a nombre del músico (timbrados y con error)."""
    artist_id = await _require_cobra(scope)
    rows = (
        await db.execute(
            select(Cfdi).where(Cfdi.artist_id == artist_id).order_by(Cfdi.id.desc())
        )
    ).scalars().all()
    return {"items": [_cfdi_out(c) for c in rows]}


@router.get("/cfdis/{cfdi_id}/file/{fmt}")
async def download_cfdi(cfdi_id: int, fmt: str, scope: CurrentScope, db: DbSession):
    """Descarga el PDF o XML de un CFDI timbrado del músico."""
    from fastapi.responses import Response

    artist_id = await _require_cobra(scope)
    cfdi = await db.get(Cfdi, cfdi_id)
    if cfdi is None or cfdi.artist_id != artist_id:
        raise HTTPException(status_code=404, detail="CFDI no encontrado.")
    if cfdi.status != "stamped" or not cfdi.facturama_id:
        raise HTTPException(status_code=409, detail="Este CFDI todavía no está timbrado.")
    if fmt not in ("pdf", "xml"):
        raise HTTPException(status_code=400, detail="Formato no válido.")
    client = get_facturama()
    try:
        data = await client.get_cfdi_file(cfdi.facturama_id, fmt)
    except FacturamaError as exc:
        raise HTTPException(status_code=502, detail=exc.message)
    media = "application/pdf" if fmt == "pdf" else "application/xml"
    fname = f"CFDI_{cfdi.uuid or cfdi.id}.{fmt}"
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# --- Shows (publicaciones) ------------------------------------------------

@router.get("/artist/shows", response_model=list[ShowOut])
async def list_my_shows(scope: CurrentScope, db: DbSession):
    artist_id = await _require_artist(scope)
    res = await db.execute(
        select(Show).options(*_SHOW_RELS).where(Show.artist_id == artist_id).order_by(Show.show_name)
    )
    return list(res.scalars().unique().all())


def _afinidad_valida(respuestas) -> dict | None:
    """Filtra y comprueba las diez respuestas del cuestionario de un show.

    Se valida aquí y no sólo en el formulario porque una respuesta que no está
    en su lista no cruza contra ninguna matriz: ese show dejaría de aparecer
    recomendado y nadie sabría por qué. Lo que no es una pregunta conocida se
    descarta en silencio -el alta puede mandar de más-, pero una opción
    inventada revienta.
    """
    if not respuestas:
        return None
    limpio: dict = {}
    for pregunta, valor in respuestas.items():
        if pregunta not in af.PREGUNTAS or valor in (None, "", []):
            continue
        try:
            af._indices(pregunta, valor)
        except af.RespuestaInvalida as e:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                detail=str(e)) from e
        limpio[pregunta] = valor
    return limpio or None


def _nuevo_show(artist_id: int, payload: ShowCreate) -> Show:
    datos = payload.model_dump(exclude={"seasonal_rates", "images"})
    datos["afinidad"] = _afinidad_valida(datos.get("afinidad"))
    show = Show(artist_id=artist_id, **datos)
    for rate in payload.seasonal_rates:
        show.seasonal_rates.append(ShowSeasonalRate(**rate.model_dump()))
    for img in payload.images:
        show.images.append(ShowImage(**img.model_dump()))
    return show


def _aplicar_show(show: Show, payload: ShowUpdate) -> None:
    data = payload.model_dump(exclude_unset=True)
    rates = data.pop("seasonal_rates", None)
    images = data.pop("images", None)
    if "afinidad" in data:
        data["afinidad"] = _afinidad_valida(data["afinidad"])
    for field, value in data.items():
        setattr(show, field, value)
    if rates is not None:
        # El calendario de temporadas se reemplaza completo con lo que llega.
        show.seasonal_rates.clear()
        for rate in rates:
            show.seasonal_rates.append(ShowSeasonalRate(**rate))
    if images is not None:
        # La galería también se reemplaza: el editor manda la lista final.
        show.images.clear()
        for img in images:
            show.images.append(ShowImage(**img))


@router.post("/artist/shows", response_model=ShowOut, status_code=status.HTTP_201_CREATED)
async def add_my_show(payload: ShowCreate, scope: CurrentScope, db: DbSession):
    show = _nuevo_show(await _require_ficha_propia(scope), payload)
    db.add(show)
    await db.commit()
    return await _load_show(db, show.id)


@router.patch("/artist/shows/{show_id}", response_model=ShowOut)
async def update_my_show(show_id: int, payload: ShowUpdate, scope: CurrentScope, db: DbSession):
    artist_id = await _require_ficha_propia(scope)
    _aplicar_show(await _own_show_or_404(db, artist_id, show_id), payload)
    await db.commit()
    return await _load_show(db, show_id)


@router.delete("/artist/shows/{show_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_show(show_id: int, scope: CurrentScope, db: DbSession):
    artist_id = await _require_ficha_propia(scope)
    show = await _own_show_or_404(db, artist_id, show_id)
    await db.delete(show)
    await db.commit()


@router.get("/artist/notifications")
async def my_notifications(scope: CurrentScope, db: DbSession):
    """The logged-in artist's bell inbox (avisos de actuaciones)."""
    artist_id = getattr(scope, "artist_id", None)
    if not artist_id:
        return {"unread": 0, "items": []}
    rows = (await db.execute(
        select(ArtistNotification)
        .where(ArtistNotification.artist_id == artist_id)
        .order_by(ArtistNotification.created_at.desc())
        .limit(50)
    )).scalars().all()
    return {
        "unread": sum(1 for r in rows if not r.is_read),
        "items": [{
            "id": r.id,
            "kind": r.kind,
            "title": r.title,
            "body": r.body,
            "starts_at": r.starts_at.isoformat() if r.starts_at else None,
            "is_read": r.is_read,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in rows],
    }


@router.post("/artist/notifications/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_notifications_read(scope: CurrentScope, db: DbSession):
    """Mark all of the artist's notifications as read (opened the bell)."""
    artist_id = getattr(scope, "artist_id", None)
    if artist_id:
        await db.execute(
            update(ArtistNotification)
            .where(
                ArtistNotification.artist_id == artist_id,
                ArtistNotification.is_read.is_(False),
            )
            .values(is_read=True)
        )
        await db.commit()


# --- Contrato (aceptación electrónica = firma) ----------------------------

async def _current_contract(db: DbSession):
    return (await db.execute(
        select(ContractTemplate)
        .where(ContractTemplate.slug == ARTIST_CONTRACT_SLUG)
        .order_by(ContractTemplate.version.desc())
        .limit(1)
    )).scalar_one_or_none()


@router.get("/contract")
async def my_contract(scope: CurrentScope, db: DbSession):
    """Contrato vigente + si el artista ya aceptó ESTA versión.

    El front usa `required` para bloquear el onboarding / mostrar el aviso a los
    artistas que ya existen hasta que acepten la versión actual.
    """
    artist_id = await _require_artist(scope)
    cur = await _current_contract(db)
    if cur is None:
        # Sin contrato publicado todavía: no hay nada que aceptar, no bloquea.
        return {"required": False, "accepted": True, "contract": None}
    accepted = (await db.execute(
        select(ContractAcceptance).where(
            ContractAcceptance.slug == ARTIST_CONTRACT_SLUG,
            ContractAcceptance.version == cur.version,
            ContractAcceptance.user_id == scope.user.id,
        ).limit(1)
    )).scalar_one_or_none()
    return {
        "required": accepted is None,
        "accepted": accepted is not None,
        "accepted_at": accepted.created_at.isoformat() if accepted and accepted.created_at else None,
        "contract": {"version": cur.version, "title": cur.title, "body": cur.body},
    }


@router.post("/contract/accept")
async def accept_contract(request: Request, scope: CurrentScope, db: DbSession):
    """Registra la aceptación de la versión vigente = firma electrónica.

    Guarda nombre, versión, fecha/hora (created_at) e IP. Idempotente: aceptar
    dos veces la misma versión no duplica la constancia.
    """
    artist_id = await _require_artist(scope)
    cur = await _current_contract(db)
    if cur is None:
        raise HTTPException(status_code=404, detail="No hay un contrato vigente por aceptar.")
    existing = (await db.execute(
        select(ContractAcceptance).where(
            ContractAcceptance.slug == ARTIST_CONTRACT_SLUG,
            ContractAcceptance.version == cur.version,
            ContractAcceptance.user_id == scope.user.id,
        ).limit(1)
    )).scalar_one_or_none()
    if existing is None:
        fwd = request.headers.get("x-forwarded-for", "")
        ip = (fwd.split(",")[0].strip() if fwd else "") or (request.client.host if request.client else None)
        db.add(ContractAcceptance(
            slug=ARTIST_CONTRACT_SLUG,
            version=cur.version,
            user_id=scope.user.id,
            artist_id=artist_id,
            signer_name=scope.user.full_name,
            ip=ip,
        ))
        await db.commit()
    return {"accepted": True, "version": cur.version}


# --- Availability blocks (vacaciones / enfermedad) ------------------------

@router.get("/blocked-dates")
async def list_blocked_dates(scope: CurrentScope, db: DbSession):
    """Days the artist marked as unavailable, as 'YYYY-MM-DD' strings."""
    artist_id = await _require_artist(scope)
    rows = (await db.execute(
        select(ArtistBlockedDate)
        .where(ArtistBlockedDate.artist_id == artist_id)
        .order_by(ArtistBlockedDate.blocked_on)
    )).scalars().all()
    return [{"date": r.blocked_on.isoformat(), "reason": r.reason} for r in rows]


@router.post("/blocked-dates", status_code=status.HTTP_201_CREATED)
async def block_date(payload: BlockedDateIn, scope: CurrentScope, db: DbSession):
    """Block one day (idempotent: re-blocking just refreshes the reason)."""
    artist_id = await _require_artist(scope)
    existing = (await db.execute(
        select(ArtistBlockedDate).where(
            ArtistBlockedDate.artist_id == artist_id,
            ArtistBlockedDate.blocked_on == payload.date,
        )
    )).scalar_one_or_none()
    if existing:
        existing.reason = payload.reason
    else:
        db.add(ArtistBlockedDate(artist_id=artist_id, blocked_on=payload.date, reason=payload.reason))
    await db.commit()
    return {"date": payload.date.isoformat(), "reason": payload.reason}


@router.delete("/blocked-dates/{day}", status_code=status.HTTP_204_NO_CONTENT)
async def unblock_date(day: date_cls, scope: CurrentScope, db: DbSession):
    """Remove a block so the day is bookable again."""
    artist_id = await _require_artist(scope)
    await db.execute(
        sa_delete(ArtistBlockedDate).where(
            ArtistBlockedDate.artist_id == artist_id,
            ArtistBlockedDate.blocked_on == day,
        )
    )
    await db.commit()


# --- Tarifas especiales por cliente (descuento del músico a un hotel/cadena) ---

class ClientRateIn(BaseModel):
    company_id: int | None = None
    group_id: int | None = None
    special_price: float | None = None
    discount_pct: float | None = None


def _rate_out(r: ArtistClientRate, company_name=None, group_name=None) -> dict:
    return {
        "id": r.id,
        "company_id": r.company_id,
        "group_id": r.group_id,
        "company_name": company_name,
        "group_name": group_name,
        "special_price": float(r.special_price) if r.special_price is not None else None,
        "discount_pct": float(r.discount_pct) if r.discount_pct is not None else None,
    }


@router.get("/artist/clients")
async def my_clients(scope: CurrentScope, db: DbSession):
    """Todos los hoteles y cadenas de la plataforma (no solo con los que ya trabajó),
    para que el músico pueda fijarle una tarifa especial a cualquiera. David: darle
    la lista completa da más margen para negociar volumen; cada músico gestiona sus
    propios descuentos."""
    await _require_artist(scope)
    crows = (await db.execute(
        select(Company.id, Company.name, Company.group_id).order_by(Company.name)
    )).all()
    grows = (await db.execute(
        select(PropertyGroup.id, PropertyGroup.name).order_by(PropertyGroup.name)
    )).all()
    return {
        "companies": [{"id": cid, "name": name, "group_id": gid} for cid, name, gid in crows],
        "groups": [{"id": gid, "name": name} for gid, name in grows],
    }


@router.get("/artist/client-rates")
async def list_client_rates(scope: CurrentScope, db: DbSession):
    artist_id = await _require_cobra(scope)
    rates = (await db.execute(
        select(ArtistClientRate).where(ArtistClientRate.artist_id == artist_id)
    )).scalars().all()
    cids = {r.company_id for r in rates if r.company_id}
    gids = {r.group_id for r in rates if r.group_id}
    cnames = {cid: nm for cid, nm in (await db.execute(
        select(Company.id, Company.name).where(Company.id.in_(cids)))).all()} if cids else {}
    gnames = {gid: nm for gid, nm in (await db.execute(
        select(PropertyGroup.id, PropertyGroup.name).where(PropertyGroup.id.in_(gids)))).all()} if gids else {}
    return [_rate_out(r, cnames.get(r.company_id), gnames.get(r.group_id)) for r in rates]


@router.post("/artist/client-rates", status_code=status.HTTP_201_CREATED)
async def add_client_rate(payload: ClientRateIn, scope: CurrentScope, db: DbSession):
    artist_id = await _require_cobra(scope)
    if not payload.company_id and not payload.group_id:
        raise HTTPException(status_code=400, detail="Elige un hotel o una cadena.")
    if payload.company_id and payload.group_id:
        raise HTTPException(status_code=400, detail="Elige un hotel O una cadena, no ambos.")
    if payload.special_price is None and payload.discount_pct is None:
        raise HTTPException(status_code=400, detail="Indica un precio especial o un % de descuento.")
    if payload.discount_pct is not None and not (0 < payload.discount_pct <= 100):
        raise HTTPException(status_code=400, detail="El descuento debe estar entre 1 y 100%.")
    # Reemplaza cualquier tarifa previa para el mismo cliente.
    await db.execute(sa_delete(ArtistClientRate).where(
        ArtistClientRate.artist_id == artist_id,
        ArtistClientRate.company_id == payload.company_id,
        ArtistClientRate.group_id == payload.group_id,
    ))
    rate = ArtistClientRate(
        artist_id=artist_id, company_id=payload.company_id, group_id=payload.group_id,
        special_price=payload.special_price, discount_pct=payload.discount_pct,
    )
    db.add(rate)
    await db.commit()
    await db.refresh(rate)
    return _rate_out(rate)


@router.delete("/artist/client-rates/{rate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client_rate(rate_id: int, scope: CurrentScope, db: DbSession):
    artist_id = await _require_cobra(scope)
    await db.execute(sa_delete(ArtistClientRate).where(
        ArtistClientRate.id == rate_id, ArtistClientRate.artist_id == artist_id))
    await db.commit()


# --- Mis músicos (productoras) --------------------------------------------
#
# Una productora con 100 músicos no puede llevarles la agenda a mano (David,
# 28/08). La salida no es meterlos como contactos sueltos dentro de la ficha de
# la empresa: es que cada uno sea una FICHA de verdad, colgada de la suya. Así
# heredan gratis lo que ya está construido y va por artist_id -bloquear fechas,
# desaparecer del catálogo ese día, no admitir doble agenda, historial propio- y
# el aviso de contratación le llega a él y no sólo a la empresa.
#
# Quien cobra sigue siendo la empresa: por eso estas fichas no llevan
# facturación (ver _require_cobra y _FISCALES).


class MusicoIn(BaseModel):
    stage_name: str
    email: str
    phone: str | None = None
    artist_type: str | None = None


def _musico_out(a: Artist, tiene_cuenta: bool) -> dict:
    return {
        "id": a.id,
        "stage_name": a.stage_name,
        "email": a.email,
        "phone": a.phone,
        "artist_type": a.artist_type,
        "profile_image_url": a.profile_image_url,
        "is_active": a.is_active,
        # Que EXISTA la cuenta, que es lo único que se puede afirmar: no
        # guardamos el último acceso, así que no hay forma de saber si ya entró
        # a poner su contraseña. Por eso el botón de reenviar la invitación se
        # ofrece siempre, en vez de inventar un "pendiente" que no sabemos.
        "tiene_cuenta": tiene_cuenta,
    }


async def _require_productora(scope: CurrentScope, db: DbSession) -> int:
    """El artist_id de quien SÍ puede dar de alta músicos.

    Dar de alta crea una cuenta en SHOWMA y manda un correo a la dirección que
    escriban. Eso no puede quedar abierto a cualquier proveedor con sesión: sería
    una forma de mandar correo desde el dominio de SHOWMA a quien sea. El permiso
    lo prende el administrador en la ficha, uno por uno.

    Y un solo nivel: el que ya cuelga de una empresa no arma equipo propio.
    Productoras dentro de productoras no existen en el negocio y convertirían
    cada consulta de alcance en un recorrido de árbol.
    """
    artist_id = await _require_artist(scope)
    yo = await db.get(Artist, artist_id)
    if yo is not None and yo.parent_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Perteneces a una empresa, así que no puedes tener equipo propio.",
        )
    if yo is None or not yo.is_productora:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tu ficha no está dada de alta como productora. Pídeselo a SHOWMA.",
        )
    return artist_id


async def _mi_musico(db: DbSession, productora_id: int, musico_id: int) -> Artist:
    """El músico que cuelga de MI ficha, o 404.

    404 y no 403 a propósito: si contestara "existe pero no es tuyo", una
    productora podría ir probando números para averiguar quién más está dado de
    alta en SHOWMA.
    """
    a = await db.get(Artist, musico_id)
    if a is None or a.parent_id != productora_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Ese músico no está en tu equipo")
    return a


@router.get("/musicos")
async def list_my_musicians(scope: CurrentScope, db: DbSession):
    productora_id = await _require_artist(scope)
    filas = (await db.execute(
        select(Artist).where(Artist.parent_id == productora_id)
        .order_by(Artist.stage_name)
    )).scalars().all()
    return [_musico_out(a, bool(a.user_id)) for a in filas]


@router.post("/musicos", status_code=status.HTTP_201_CREATED)
async def add_my_musician(payload: MusicoIn, scope: CurrentScope, db: DbSession):
    """Da de alta a un músico del equipo y le manda su invitación.

    La productora NO elige la contraseña. Se crea la cuenta con una al azar que
    nadie llega a saber y se le manda al músico el enlace para que ponga la
    suya. Si la empresa la supiera podría entrar como él y aceptar o cancelar
    contrataciones en su nombre, y entonces lo de que el músico maneja su propia
    disponibilidad sería mentira.
    """
    productora_id = await _require_productora(scope, db)
    musico, user = await _crear_musico(db, productora_id, payload)
    await db.commit()
    await db.refresh(musico)
    enviado = await _invitar(db, user)
    return {**_musico_out(musico, True), "invitacion_enviada": enviado}


async def _crear_musico(
    db: DbSession, productora_id: int, payload: MusicoIn
) -> tuple[Artist, User]:
    """Crea la cuenta y la ficha del músico. NO hace commit ni manda el correo.

    Sin commit a propósito: el alta por lista mete muchos de un golpe y quien
    llama decide dónde cierra. Y sin correo, porque mandar 200 invitaciones
    dentro de una sola petición la tumbaría por tiempo.
    """
    correo = (payload.email or "").strip().lower()
    if not correo:
        raise HTTPException(status_code=422, detail="Hace falta el correo del músico.")
    ya = (await db.execute(select(User).where(User.email == correo))).scalar_one_or_none()
    if ya is not None:
        # Si ya tiene cuenta en SHOWMA no se le crea otra ni se le engancha por
        # las malas: ese perfil es suyo y tiene su propio historial. Lo correcto
        # es que él acepte unirse, y eso todavía no está construido.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ese correo ya tiene cuenta en SHOWMA. Pídele que se una desde su perfil.",
        )

    role = (await db.execute(select(Role).where(Role.name == "artist"))).scalar_one_or_none()
    user = User(
        email=correo,
        full_name=payload.stage_name,
        hashed_password=security.hash_password(passwords.temp_password(24)),
        role_id=role.id if role else None,
    )
    db.add(user)
    await db.flush()

    musico = Artist(
        user_id=user.id,
        parent_id=productora_id,
        stage_name=payload.stage_name,
        artist_type=payload.artist_type,
        phone=payload.phone,
        email=correo,
    )
    db.add(musico)
    await db.flush()
    return musico, user


class LoteIn(BaseModel):
    """Lista pegada de un jalón. Tope de 500 por petición."""
    musicos: list[MusicoIn]


@router.post("/musicos/lote")
async def add_my_musicians_bulk(payload: LoteIn, scope: CurrentScope, db: DbSession):
    """Da de alta una lista completa de músicos, SIN mandar las invitaciones.

    Son dos pasos y no uno por una razón práctica: 200 correos dentro de una
    misma petición se tardarían minutos y el navegador cortaría a la mitad, sin
    que nadie supiera cuántos alcanzaron a salir. Aquí se crean las cuentas, que
    es lo rápido y lo que no se puede perder, y las invitaciones salen después de
    una en una, con su avance a la vista y pudiendo reintentar las que fallen.

    Cada renglón se cierra por su cuenta: uno con el correo repetido no tumba a
    los otros 199, sale en la lista de rechazados con su motivo. Un `rollback`
    general obligaría a la empresa a depurar 200 renglones a ciegas para volver
    a intentarlo.
    """
    productora_id = await _require_productora(scope, db)
    if len(payload.musicos) > 500:
        raise HTTPException(
            status_code=422,
            detail="Máximo 500 por lista. Pártela en varias.",
        )

    creados: list[dict] = []
    rechazados: list[dict] = []
    # El repetido DENTRO de la propia lista sí lo caza la consulta -cada alta
    # hace flush y la siguiente ya lo ve-, pero contestaría "ese correo ya tiene
    # cuenta en SHOWMA, pídele que se una", que manda a la empresa a buscar un
    # perfil ajeno que no existe. Lo que pasó es que lo escribieron dos veces.
    vistos: set[str] = set()
    for fila in payload.musicos:
        correo = (fila.email or "").strip().lower()
        if correo in vistos:
            rechazados.append({"stage_name": fila.stage_name, "email": correo,
                               "motivo": "Ese correo viene repetido en tu lista."})
            continue
        try:
            musico, _ = await _crear_musico(db, productora_id, fila)
        except HTTPException as e:
            rechazados.append({"stage_name": fila.stage_name, "email": correo,
                               "motivo": str(e.detail)})
            continue
        vistos.add(correo)
        creados.append(_musico_out(musico, True))
    await db.commit()
    return {"creados": creados, "rechazados": rechazados}


async def _invitar(db: DbSession, user: User) -> bool:
    """Le manda al músico el enlace para poner su contraseña.

    Devuelve si salió el correo. Que falle NO tumba el alta: la ficha ya existe
    y la empresa puede reintentar la invitación. Al revés -perder el alta porque
    el SMTP está caído- sería mucho peor.
    """
    if not mailer.is_configured():
        return False
    try:
        raw, _ = await passwords.issue_token(db, user, requested_by="productora")
        asunto, texto, html = mailer.reset_email(
            user.full_name, passwords.reset_link(raw), settings.RESET_TOKEN_MINUTES
        )
        return await mailer.send(user.email, asunto, texto, html)
    except Exception:  # noqa: BLE001 - la invitación es reintentable, el alta no
        return False


@router.post("/musicos/{musico_id}/invitar")
async def reinvite_my_musician(musico_id: int, scope: CurrentScope, db: DbSession):
    productora_id = await _require_artist(scope)
    musico = await _mi_musico(db, productora_id, musico_id)
    if not musico.user_id:
        raise HTTPException(status_code=409, detail="Ese músico no tiene cuenta.")
    user = await db.get(User, musico.user_id)
    if user is None:
        raise HTTPException(status_code=409, detail="Ese músico no tiene cuenta.")
    return {"invitacion_enviada": await _invitar(db, user)}


@router.delete("/musicos/{musico_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_my_musician(musico_id: int, scope: CurrentScope, db: DbSession):
    """Saca al músico del equipo. NO lo borra.

    Se queda con su cuenta, su ficha y su historial, que es justo lo que se le
    prometió al darlo de alta. Borrarlo se llevaría por delante las actuaciones
    que sí ocurrieron y las reseñas que los hoteles le escribieron.
    """
    productora_id = await _require_artist(scope)
    musico = await _mi_musico(db, productora_id, musico_id)
    musico.parent_id = None
    await db.commit()


# --- La productora gestiona la ficha y los shows de los suyos -------------
#
# "El perfil sería gestionado, visto y cobrado por la productora" (David,
# 02/09). No es comodidad: la empresa NO conoce la contraseña de sus músicos -
# eso es a propósito, para que no pueda aceptar contrataciones en su nombre-, así
# que si no pudiera editar desde aquí, armar un catálogo de 200 perfiles sería
# imposible. La cuenta del músico queda para bloquear fechas y ver su agenda.


@router.get("/musicos/{musico_id}", response_model=ArtistOut)
async def get_my_musician(musico_id: int, scope: CurrentScope, db: DbSession):
    """La ficha COMPLETA de uno de los suyos, para poder editarla.

    Hace falta aparte de la lista: la lista trae lo justo para pintar la tabla, y
    un formulario cargado con la mitad de los campos vacíos GUARDA esos vacíos y
    le borra la bio y la ciudad a alguien que sí las tenía.
    """
    productora_id = await _require_productora(scope, db)
    await _mi_musico(db, productora_id, musico_id)
    return await _ficha_out(db, await _load_artist(db, musico_id))


@router.patch("/musicos/{musico_id}", response_model=ArtistOut)
async def update_my_musician(
    musico_id: int, payload: ArtistUpdate, scope: CurrentScope, db: DbSession
):
    productora_id = await _require_productora(scope, db)
    await _mi_musico(db, productora_id, musico_id)
    artist = await _load_artist(db, musico_id)
    # Mismo filtro que la ficha propia: ni el sello de verificado, ni el permiso
    # de productora, ni el plan Partner, ni datos fiscales. Que sea la empresa
    # quien escribe no agranda lo que se puede escribir.
    _aplicar_ficha(artist, payload)
    await db.commit()
    return await _ficha_out(db, await _load_artist(db, musico_id))


@router.get("/musicos/{musico_id}/shows", response_model=list[ShowOut])
async def list_my_musician_shows(musico_id: int, scope: CurrentScope, db: DbSession):
    productora_id = await _require_productora(scope, db)
    await _mi_musico(db, productora_id, musico_id)
    res = await db.execute(
        select(Show).options(*_SHOW_RELS).where(Show.artist_id == musico_id).order_by(Show.show_name)
    )
    return list(res.scalars().unique().all())


@router.post("/musicos/{musico_id}/shows", response_model=ShowOut,
             status_code=status.HTTP_201_CREATED)
async def add_my_musician_show(
    musico_id: int, payload: ShowCreate, scope: CurrentScope, db: DbSession
):
    productora_id = await _require_productora(scope, db)
    await _mi_musico(db, productora_id, musico_id)
    show = _nuevo_show(musico_id, payload)
    db.add(show)
    await db.commit()
    return await _load_show(db, show.id)


@router.patch("/musicos/{musico_id}/shows/{show_id}", response_model=ShowOut)
async def update_my_musician_show(
    musico_id: int, show_id: int, payload: ShowUpdate, scope: CurrentScope, db: DbSession
):
    productora_id = await _require_productora(scope, db)
    await _mi_musico(db, productora_id, musico_id)
    # El show tiene que ser de ESE músico, no de cualquiera del equipo: si sólo
    # comprobara el músico, mandando otro show_id se editaría el de un tercero.
    _aplicar_show(await _own_show_or_404(db, musico_id, show_id), payload)
    await db.commit()
    return await _load_show(db, show_id)


@router.delete("/musicos/{musico_id}/shows/{show_id}",
               status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_musician_show(
    musico_id: int, show_id: int, scope: CurrentScope, db: DbSession
):
    productora_id = await _require_productora(scope, db)
    await _mi_musico(db, productora_id, musico_id)
    show = await _own_show_or_404(db, musico_id, show_id)
    await db.delete(show)
    await db.commit()


@router.get("/musicos/{musico_id}/agenda")
async def my_musician_agenda(musico_id: int, scope: CurrentScope, db: DbSession):
    """Las actuaciones del músico, para la productora. CON importes.

    Al revés que la vista del músico: aquí sí van los montos, porque la empresa
    es la que cobra y necesita cuadrar lo suyo.
    """
    productora_id = await _require_productora(scope, db)
    await _mi_musico(db, productora_id, musico_id)
    filas = (await db.execute(
        select(Booking).where(
            Booking.artist_id == musico_id,
            Booking.notified_at.isnot(None),
        ).order_by(Booking.starts_at)
    )).scalars().all()
    cids = {b.company_id for b in filas if b.company_id}
    sids = {b.show_id for b in filas if b.show_id}
    companies = {c.id: c.name for c in (
        (await db.execute(select(Company).where(Company.id.in_(cids)))).scalars().all()
        if cids else []
    )}
    shows = {s.id: s.show_name for s in (
        (await db.execute(select(Show).where(Show.id.in_(sids)))).scalars().all()
        if sids else []
    )}
    return [{
        "id": b.id,
        "starts_at": b.starts_at.isoformat() if b.starts_at else None,
        "status": b.status.value if hasattr(b.status, "value") else b.status,
        "hotel": companies.get(b.company_id),
        "show": shows.get(b.show_id),
        "agreed_price": float(b.agreed_price) if b.agreed_price is not None else None,
        "currency": b.currency,
    } for b in filas]
