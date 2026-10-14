"""
FaST Navigator Backend - Configuration

Environment-based configuration using pydantic-settings.
"""

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_name: str = "FaST Navigator"
    app_version: str = "1.0.0"
    debug: bool = False
    log_level: str = "INFO"  # level for this module's own loggers; see app.logging_setup

    # API
    api_prefix: str = "/api/fast"
    cors_origins: list[str] = []  # Set via CORS_ORIGINS env var; empty = deny all cross-origin

    # Internal service-to-service auth (entity-manager, other in-cluster
    # callers -> this module's /internal/* routes). Compared with
    # hmac.compare_digest — NOT the api-gateway X-Auth-Signature HMAC format,
    # that one is user-bound (gateway -> backend proxy hop only). K8s Secret
    # `internal-service-secret` (org-level) in production. No default.
    internal_service_secret: str = ""

    # Outbound calls to other modules are signed like the api-gateway does
    # (X-Auth-Signature over an empty token and the tenant). K8s Secret in production.
    hmac_secret: str = ""

    # Platform services FaST reads (service names inside the platform namespace).
    bioorch_url: str = "http://bioorchestrator-api-service:8420"
    soil_url: str = "http://soil-module-service:8000"
    weather_api_url: str = "http://weather-api-service:8000"

    # PostgreSQL: FaST keeps its plans here, in its own `fast` schema (spec §9).
    # Never time-series/telemetry — that flows through Orion-LD subscriptions.
    # Kubernetes injects DATABASE_URL; POSTGRES_URL is the canonical name.
    # No hardcoded fallback: see require_postgres_url() below.
    postgres_url: str = Field(default="",
                              validation_alias=AliasChoices("POSTGRES_URL", "DATABASE_URL"))

    # Redis (for caching/celery - optional)
    # redis_url: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


def require_postgres_url() -> str:
    """Return POSTGRES_URL or fail fast.

    Call this from any code path that opens a PostgreSQL connection — do NOT
    hardcode a fallback DSN (platform rule: "POSTGRES_URL is MANDATORY —
    services must fail at startup if not set"). The application lifespan calls
    it at start-up, before migrating and opening the pool.
    """
    settings = get_settings()
    if not settings.postgres_url:
        raise RuntimeError(
            "POSTGRES_URL is not set. Set the POSTGRES_URL env var "
            "(K8s Secret in production) before using PostgreSQL."
        )
    return settings.postgres_url
