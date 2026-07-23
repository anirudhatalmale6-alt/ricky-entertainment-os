"""FastAPI application entrypoint."""
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.v1.router import api_router
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
