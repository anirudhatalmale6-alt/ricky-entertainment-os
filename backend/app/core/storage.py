"""Local file storage for user-uploaded media (show photos, etc.).

FTP-only deploy + no SSH means we can't install extra packages or lean on
external object storage, so uploads live on disk next to the app and are served
back by FastAPI's StaticFiles mount. Images are resized/compressed on the client
(canvas -> JPEG) before upload, so the server just validates and writes bytes —
no Pillow dependency.

Layout (works for both the repo and the cPanel deploy):
    <app_root>/static/uploads/<file>
where <app_root> is `backend/` in the repo and `ricky_app/` on the server —
the same parent that already holds static/dashboard.html.
"""
from pathlib import Path

# app/core/storage.py -> parents[2] == app_root (backend/ or ricky_app/)
_APP_ROOT = Path(__file__).resolve().parents[2]
UPLOAD_DIR = _APP_ROOT / "static" / "uploads"


def ensure_upload_dir() -> Path:
    """Create the uploads directory if needed and return it."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return UPLOAD_DIR
