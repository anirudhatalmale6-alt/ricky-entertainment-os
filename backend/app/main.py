"""FastAPI application entrypoint."""
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.v1.public import tarjeta_data
from app.api.v1.router import api_router
from app.api.deps import DbSession
from app.core.config import settings
from app.core.storage import ensure_upload_dir
from app.db.session import init_db

# The single-file dashboard lives in the repo's frontend/ during development and
# is copied next to the backend (static/) on deploy — accept either layout.
_HERE = Path(__file__).resolve()
_FRONTEND_CANDIDATES = [
    _HERE.parent.parent / "static" / "dashboard.html",       # deploy: ricky_app/static/
    _HERE.parent.parent.parent / "frontend" / "dashboard.html",  # repo: ricky-os/frontend/
]
# The artist registration hoja (3-step form) — same dual layout.
_REGISTRO_CANDIDATES = [
    _HERE.parent.parent / "static" / "registro_artista.html",
    _HERE.parent.parent.parent / "frontend" / "registro" / "registro_artista.html",
]


def _first_existing(candidates: list[Path]) -> Path | None:
    for p in candidates:
        if p.is_file():
            return p
    return None


def _frontend_file() -> Path | None:
    return _first_existing(_FRONTEND_CANDIDATES)


def _serve_html(f: Path | None, fallback: str) -> HTMLResponse:
    """Serve a single-file page, injecting the API base so the frontend knows
    where the API lives (one URL, no CORS)."""
    if f is None:
        return HTMLResponse(fallback, headers=_NO_CACHE)
    html = f.read_text(encoding="utf-8")
    inject = f"<script>window.RICKY_API={json.dumps(settings.ROOT_PATH)};</script>"
    if "</head>" in html:
        html = html.replace("</head>", inject + "</head>", 1)
    else:
        html = inject + html
    return HTMLResponse(html, headers=_NO_CACHE)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # For local/dev convenience create tables on startup.
    # Production uses Alembic migrations.
    await init_db()
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=__version__,
    lifespan=lifespan,
    root_path=settings.ROOT_PATH,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)

# User-uploaded media (show photos). Served straight from disk; immutable unique
# filenames so edge caching is fine (no no-store here).
app.mount("/uploads", StaticFiles(directory=str(ensure_upload_dir())), name="uploads")


@app.get("/health", tags=["system"])
async def health():
    return {"status": "ok", "service": settings.PROJECT_NAME, "version": __version__}


# The dashboard is a single file that we overwrite on every deploy, so it must
# never be cached by the LiteSpeed edge (LSCache) — otherwise a stale copy keeps
# being served after an upload. Send explicit no-store on the HTML entrypoint.
_NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
    "X-LiteSpeed-Cache-Control": "no-cache",
}


@app.get("/", include_in_schema=False)
async def dashboard():
    """Serve the single-file dashboard and tell it where the API lives, so the
    whole app is reachable at one URL (e.g. reenewtv.com/ricky) with no CORS."""
    return _serve_html(
        _frontend_file(),
        "<h1>RICKY Entertainment OS</h1><p>API activa en "
        f"{settings.ROOT_PATH}{settings.API_V1_PREFIX}</p>",
    )


@app.get("/master", include_in_schema=False)
async def master_console():
    """Private Master console — a hidden 'intranet' entrypoint, separate from the
    Hotel/Artist login and not linked from it. Serves the same single-file app;
    the frontend detects the /master path and boots straight into the internal
    console (admin-only; anyone else is bounced back to the sign-in)."""
    return _serve_html(
        _frontend_file(),
        "<h1>SHOWMA · Master</h1><p>Panel interno.</p>",
    )


@app.get("/registro", include_in_schema=False)
async def registro():
    """The artist registration hoja (fotos, precios, redes, datos fiscales).
    A new artist lands here after signing up, then goes to the dashboard."""
    return _serve_html(
        _first_existing(_REGISTRO_CANDIDATES),
        "<h1>Registro de artista</h1><p>Formulario no disponible.</p>",
    )


# --- Tarjeta de presentacion publica ---------------------------------------
_TARJETA_CANDIDATES = [
    _HERE.parent.parent / "static" / "tarjeta.html",
    _HERE.parent.parent.parent / "frontend" / "publico" / "tarjeta.html",
]


def _abs_url(path: str | None) -> str | None:
    """Una imagen '/uploads/x.jpg' no le sirve a WhatsApp: necesita la
    direccion completa, con dominio."""
    if not path:
        return None
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{settings.public_root}{path}"


# Las categorias se guardan sin acentos en la base; para un texto que va a leer
# una persona se pintan bien escritas.
_ACENTOS = {"Musica": "Música", "Produccion": "Producción",
            "Fotografia y Video": "Fotografía y Video"}


def _pretty(s: str | None) -> str:
    return _ACENTOS.get(s or "", s or "")


def _meta(data: dict, url: str) -> str:
    """Las etiquetas Open Graph, ARMADAS EN EL SERVIDOR.

    Esto no es un adorno: WhatsApp, Facebook y LinkedIn piden la pagina con un
    robot que NO ejecuta JavaScript. Si el titulo y la foto los pusiera el
    script al cargar, la liga pegada en un chat saldria como un renglon gris
    sin imagen — justo donde mas se va a usar esta tarjeta. Y og:title es el
    unico titulo que lee una red social: el <title> de la pagina no lo mira.
    """
    nombre = data.get("nombre") or "SHOWMA"
    genero = " · ".join(x for x in [
        (data["shows"][0].get("subcategoria") or data.get("categoria")) if data.get("shows") else data.get("categoria"),
        data.get("ciudad"),
    ] if x)
    titulo = f"{nombre} — {genero}" if genero else nombre
    # La descripcion ARRANCA con los numeros, no con la biografia. En la vista
    # previa de WhatsApp o de Instagram se leen dos renglones y ya: "12
    # actuaciones en 2 hoteles" es justo lo que un perfil de Instagram no puede
    # decir, y es la razon de que esta liga exista. La biografia va detras, si
    # cabe. (David, 27/08: "instagram... no da datos".)
    t = data.get("trayectoria") or {}
    cifras = []
    if t.get("actuaciones"):
        cifras.append(f"{t['actuaciones']} actuaciones")
    if t.get("hoteles"):
        cifras.append(f"{t['hoteles']} hotel" + ("es" if t["hoteles"] > 1 else ""))
    cal = t.get("calificacion") or {}
    if cal.get("promedio") is not None:
        n = cal.get("total") or 0
        cifras.append(f"{cal['promedio']}★ ({n} reseña" + ("s" if n != 1 else "") + ")")
    cabeza = " · ".join(cifras)

    desc = (data.get("bio") or "").strip()
    if not desc and data.get("shows"):
        s = data["shows"][0]
        desc = (s.get("descripcion")
                or f"{s.get('nombre')} · {_pretty(s.get('categoria'))}").strip(" ·")
    desc = f"{cabeza}. {desc}".strip() if cabeza else desc
    if not desc:
        desc = "Perfil de proveedor de entretenimiento en SHOWMA."
    if len(desc) > 200:
        desc = desc[:197].rstrip() + "…"
    img = _abs_url(data.get("portada"))

    def e(s: str) -> str:
        return (s.replace("&", "&amp;").replace("<", "&lt;")
                 .replace(">", "&gt;").replace('"', "&quot;"))

    tags = [
        f"<title>{e(titulo)} | SHOWMA</title>",
        f'<meta name="description" content="{e(desc)}">',
        f'<meta property="og:title" content="{e(titulo)}">',
        f'<meta property="og:description" content="{e(desc)}">',
        f'<meta property="og:type" content="profile">',
        f'<meta property="og:site_name" content="SHOWMA">',
        f'<meta property="og:url" content="{e(url)}">',
        f'<meta name="twitter:card" content="{"summary_large_image" if img else "summary"}">',
        f'<meta name="twitter:title" content="{e(titulo)}">',
        f'<meta name="twitter:description" content="{e(desc)}">',
    ]
    if img:
        tags.append(f'<meta property="og:image" content="{e(img)}">')
        tags.append(f'<meta name="twitter:image" content="{e(img)}">')
    return "\n".join(tags)


@app.get("/p/{slug}", include_in_schema=False)
async def tarjeta_publica(slug: str, db: DbSession):
    """La tarjeta de un proveedor: pagina publica, sin cuenta y sin sesion."""
    data = await tarjeta_data(db, slug)
    if data is None:
        return HTMLResponse(
            "<div style=\"font-family:system-ui;text-align:center;padding:80px 20px;color:#697089\">"
            "<h1 style=\"color:#1b1f2e;font-size:20px\">Esta tarjeta no está disponible</h1>"
            "<p style=\"margin-top:8px\">La liga puede haber cambiado o el perfil ya no está publicado.</p>"
            f"<p style=\"margin-top:22px\"><a href=\"{settings.ROOT_PATH}/\" "
            "style=\"color:#382ca1;font-weight:600\">Ir a SHOWMA</a></p></div>",
            status_code=404, headers=_NO_CACHE,
        )
    f = _first_existing(_TARJETA_CANDIDATES)
    if f is None:
        return HTMLResponse("<h1>Tarjeta no disponible</h1>", status_code=500)
    url = f"{settings.public_root}/p/{slug}"
    html = f.read_text(encoding="utf-8")
    # Los datos van EMBEBIDOS, no se piden con un fetch: la tarjeta se abre en
    # el celular de alguien que quiza esta en el lobby con mala senal, y una
    # pantalla en blanco mientras carga es una tarjeta que no se ensena.
    # El "</" escapado evita que un texto con una etiqueta dentro corte el
    # bloque <script> a la mitad.
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    inject = (
        _meta(data, url)
        + f"\n<script>window.RICKY_API={json.dumps(settings.ROOT_PATH)};"
        + f"window.TARJETA={blob};window.TARJETA_URL={json.dumps(url)};</script>"
    )
    if "<!--OG-->" in html:
        html = html.replace("<!--OG-->", inject, 1)
    elif "</head>" in html:
        html = html.replace("</head>", inject + "</head>", 1)
    else:
        html = inject + html
    return HTMLResponse(html, headers=_NO_CACHE)
