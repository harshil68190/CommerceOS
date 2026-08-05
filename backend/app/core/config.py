"""
core/config.py

Responsibility
--------------
Single source of truth for application configuration. Every environment
variable the app depends on is declared here, typed, and validated once at
process startup — nothing else in the codebase should call `os.getenv(...)`
directly. This is what lets the same code run unmodified in local dev,
CI, and production: only the environment differs, never the code.

We use pydantic-settings (Pydantic v2) so that:
  - required variables fail fast at startup with a clear error, instead of
    surfacing as a confusing runtime error deep inside a request.
  - types are validated (e.g. PORT must be an int, DEBUG must be a bool).
  - a `.env` file is supported for local development without ever needing
    that file in production (containers inject real env vars instead).
"""

import os
from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# SQLAlchemy driver strings normalized to the psycopg (v3) driver so the
# same short URLs work in Render's dashboards and our env templates.
_DRIVER_ALIASES = {
    "postgres://": "postgresql+psycopg://",
    "postgresql://": "postgresql+psycopg://",
    "postgresql+psycopg2://": "postgresql+psycopg://",
}


class Settings(BaseSettings):
    """
    Typed application settings, populated from environment variables
    (and, for local dev convenience, from a `.env` file).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- General application metadata ---------------------------------
    APP_NAME: str = "CommerceOS"
    ENVIRONMENT: str = Field(
        default="development",
        description="One of: development, staging, production, test.",
    )
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # --- Server ----------------------------------------------------------
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    # Number of uvicorn worker processes. In production a value > 1 is
    # recommended; each worker gets its own DB connection pool sized by
    # DB_POOL_SIZE below. Local dev / tests keep the default of 1.
    WEB_CONCURRENCY: int = 1

    # --- Logging ----------------------------------------------------------
    # Explicit log level override. Defaults derive from DEBUG (DEBUG ->
    # "DEBUG", else "INFO"); production should set LOG_LEVEL=INFO explicitly.
    LOG_LEVEL: str | None = None

    # --- Database ----------------------------------------------------------
    # Standard SQLAlchemy connection URL, e.g.:
    # postgresql+psycopg://user:password@host:5432/dbname
    DATABASE_URL: str = Field(
        ...,
        description="SQLAlchemy database connection URL for PostgreSQL.",
    )
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT_SECONDS: int = 30
    DB_ECHO: bool = False  # SQL statement logging — dev-only, never in prod

    # --- Migrations ----------------------------------------------------------
    # Whether the container's entrypoint should run `alembic upgrade head`
    # on startup. True for local dev / single-node Compose; for production
    # Render runs migrations as a separate one-off job, so set this to
    # "false" on the web service to avoid concurrent-migration races.
    RUN_MIGRATIONS: bool = True

    # --- Redis ----------------------------------------------------------
    REDIS_URL: str = Field(
        ...,
        description="Redis connection URL, e.g. redis://host:6379/0",
    )

    # --- Security (used by later milestones, declared now so config
    #     stays centralized from the start) ---------------------------
    JWT_SECRET_KEY: str = Field(
        ...,
        description="Secret key used to sign JWTs. Must be injected via env in prod.",
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    # --- CORS ----------------------------------------------------------
    # Comma-separated list of allowed origins, parsed into a list below.
    CORS_ORIGINS: str = "http://localhost:5173"

    @field_validator("ENVIRONMENT")
    @classmethod
    def _validate_environment(cls, value: str) -> str:
        allowed = {"development", "staging", "production", "test"}
        if value not in allowed:
            raise ValueError(f"ENVIRONMENT must be one of {allowed}, got '{value}'")
        return value

    @field_validator("DEBUG")
    @classmethod
    def _debug_forbidden_in_production(cls, value: bool, info) -> bool:
        # Fail fast with a clear message rather than accidentally serving
        # a production site with debug/traceback handling enabled.
        environment = info.data.get("ENVIRONMENT")
        if environment == "production" and value:
            raise ValueError(
                "DEBUG must be False when ENVIRONMENT=production. "
                "Set DEBUG=false in the production environment."
            )
        return value

    @field_validator("DATABASE_URL")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        """Normalize common Postgres URL driver prefixes to psycopg v3."""
        for prefix, replacement in _DRIVER_ALIASES.items():
            if value.lower().startswith(prefix):
                return replacement + value[len(prefix):]
        return value

    @property
    def cors_origins_list(self) -> List[str]:
        """Parse the comma-separated CORS_ORIGINS env var into a clean list."""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def effective_log_level(self) -> str:
        """Log level to use: explicit LOG_LEVEL wins, else derived from DEBUG."""
        if self.LOG_LEVEL:
            return self.LOG_LEVEL.upper()
        if self.DEBUG:
            return "DEBUG"
        return "INFO"


@lru_cache
def get_settings() -> Settings:
    """
    Returns a cached Settings instance.

    `lru_cache` ensures the environment is only parsed/validated once per
    process, and gives every module a single shared settings object via
    dependency injection: `settings: Settings = Depends(get_settings)`
    in routers, or a plain `get_settings()` call in non-request code.
    """
    # Tests select their configuration explicitly through this variable.
    # Production keeps the normal .env default.
    return Settings(_env_file=os.getenv("COMMERCEOS_ENV_FILE", ".env"))
