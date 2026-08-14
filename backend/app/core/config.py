"""Application configuration.

Loaded from environment variables (or a .env file). Uses SQLite by default for
local development so the project runs out of the box; set DATABASE_URL to a
PostgreSQL DSN for production.
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env by absolute path (backend root / app root), not relative to the
# process CWD. Under cPanel Passenger the working directory is not guaranteed to
# be the app root, and a missing .env would silently fall back to insecure
# defaults (wrong ROOT_PATH, default SECRET_KEY). This works for both layouts:
#   repo:   backend/app/core/config.py -> backend/.env
#   deploy: ricky_app/app/core/config.py -> ricky_app/.env
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE), env_file_encoding="utf-8", extra="ignore"
    )

    # Project
    PROJECT_NAME: str = "RICKY Entertainment OS"
    API_V1_PREFIX: str = "/api/v1"
    ENVIRONMENT: str = "development"
    # Sub-path the app is served under (e.g. "/ricky" behind cPanel Passenger).
    # Empty for a root deploy or local uvicorn. The frontend reads this to build
    # its API base, and FastAPI uses it as root_path for docs/openapi.
    ROOT_PATH: str = ""

    # Database - SQLite for dev, PostgreSQL (asyncpg) for prod
    #   postgresql+asyncpg://user:pass@host:5432/dbname
    DATABASE_URL: str = "sqlite+aiosqlite:///./ricky.db"

    # Security / JWT
    SECRET_KEY: str = "change-me-in-production-please-use-a-long-random-secret"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1 day
    ALGORITHM: str = "HS256"

    # 2FA
    TOTP_ISSUER: str = "RICKY Entertainment OS"

    # CORS
    CORS_ORIGINS: str = "*"

    # --- Facturama (CFDI e-invoicing / timbrado) -----------------------
    # SHOWMA emite CFDI reales a nombre de cada músico (modalidad Multiemisor:
    # cada músico factura con su propio RFC tras subir su CSD una sola vez).
    # Deja FACTURAMA_ENABLED en False hasta tener credenciales; así la
    # plataforma corre igual y la sección de facturación se muestra "no
    # configurada" en lugar de romper. Sandbox = ambiente de pruebas (gratis,
    # sin folios reales); en producción se apunta a api.facturama.mx.
    FACTURAMA_ENABLED: bool = False
    FACTURAMA_USER: str = ""
    FACTURAMA_PASSWORD: str = ""
    FACTURAMA_SANDBOX: bool = True
    # Raya de arranque: NO se factura ninguna actuación anterior a esta fecha
    # (formato AAAA-MM-DD). En la base conviven actuaciones de demostración y de
    # pruebas; sin esta raya el primer cierre en producción intentaría timbrarlas
    # como reales. Vacío = sin límite (sólo para desarrollo).
    FACTURACION_DESDE: str = ""

    # --- Correo saliente (SMTP) ----------------------------------------
    # Recuperación de contraseña y avisos de actuaciones. Si SMTP_HOST va vacío
    # la plataforma funciona igual: los avisos siguen dentro (campanita) y el
    # enlace de recuperación queda disponible en MASTER para pasarlo a mano.
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_SECURITY: str = "starttls"      # starttls | ssl | none
    SMTP_FROM: str = ""                  # si va vacío se usa SMTP_USER
    SMTP_FROM_NAME: str = "SHOWMA"
    # Dirección pública desde la que se arma el enlace del correo.
    PUBLIC_BASE_URL: str = "http://localhost:8000"
    # Vigencia del enlace de recuperación.
    RESET_TOKEN_MINUTES: int = 60
    # Interruptor general de los avisos por correo (actuaciones y chat). Se puede
    # apagar sin tocar el SMTP, que la recuperación de contraseña sí lo necesita.
    NOTIFY_EMAIL: bool = True

    @property
    def mail_from(self) -> str:
        return self.SMTP_FROM or self.SMTP_USER

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def facturacion_desde_date(self):
        """FACTURACION_DESDE como date, o None si no se configuró."""
        from datetime import date as _date
        try:
            return _date.fromisoformat(self.FACTURACION_DESDE.strip())
        except (AttributeError, ValueError):
            return None

    @property
    def facturama_base_url(self) -> str:
        return (
            "https://apisandbox.facturama.mx"
            if self.FACTURAMA_SANDBOX
            else "https://api.facturama.mx"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
