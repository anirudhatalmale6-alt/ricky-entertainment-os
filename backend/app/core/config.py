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

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
