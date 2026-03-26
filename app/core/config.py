from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    PROJECT_NAME: str = Field(default="Pro Admin API")
    VERSION: str = Field(default="1.0.0")
    API_V1_STR: str = Field(default="/api/v1")
    ROOT_PATH: str = Field(default="")

    APP_ENV: str = Field(default="development")
    APP_HOST: str = Field(default="0.0.0.0")
    APP_PORT: int = Field(default=8000)
    APP_WORKERS: int = Field(default=2)
    APP_TIMEOUT: int = Field(default=120)
    APP_GRACEFUL_TIMEOUT: int = Field(default=30)

    APP_TRUSTED_HOSTS: str = Field(default="*")
    APP_FORCE_HTTPS: bool = Field(default=False)

    APP_ENABLE_DOCS: bool = Field(default=True)
    APP_ENABLE_REDOC: bool = Field(default=False)

    APP_SESSION_SECRET_KEY: str = Field(
        default="change-me-in-production",
    )
    APP_SESSION_COOKIE: str = Field(default="proadmin_session")
    APP_SESSION_MAX_AGE: int = Field(default=1800)
    APP_SESSION_SAME_SITE: str = Field(default="lax")
    APP_SESSION_HTTPS_ONLY: bool = Field(default=False)
    APP_SESSION_DOMAIN: str | None = Field(default=None)

    @property
    def is_production(self) -> bool:
        return self.APP_ENV.strip().lower() in {"prod", "production"}

    @property
    def trusted_hosts(self) -> list[str]:
        raw = self.APP_TRUSTED_HOSTS.strip()
        if not raw:
            return ["*"]
        return [part.strip() for part in raw.split(",") if part.strip()] or ["*"]

    @property
    def docs_url(self) -> str | None:
        return "/docs" if self.APP_ENABLE_DOCS else None

    @property
    def redoc_url(self) -> str | None:
        return "/redoc" if self.APP_ENABLE_REDOC else None

    @property
    def openapi_url(self) -> str | None:
        if not self.APP_ENABLE_DOCS and not self.APP_ENABLE_REDOC:
            return None
        return f"{self.API_V1_STR}/openapi.json"

    @field_validator("APP_SESSION_SAME_SITE")
    @classmethod
    def _validate_same_site(cls, value: str) -> str:
        normalized = str(value or "").strip().lower()
        if normalized not in {"lax", "strict", "none"}:
            raise ValueError("APP_SESSION_SAME_SITE faqat lax/strict/none bo'lishi mumkin.")
        return normalized

    @field_validator("APP_WORKERS")
    @classmethod
    def _validate_workers(cls, value: int) -> int:
        return max(1, int(value))

    @field_validator("APP_PORT")
    @classmethod
    def _validate_port(cls, value: int) -> int:
        port = int(value)
        if port < 1 or port > 65535:
            raise ValueError("APP_PORT 1-65535 oralig'ida bo'lishi kerak.")
        return port


settings = Settings()
