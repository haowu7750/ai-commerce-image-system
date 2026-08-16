from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ROOT_ENV_FILE = BACKEND_ROOT.parent / ".env.local"
BACKEND_ENV_FILE = BACKEND_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Files are loaded from least to most specific. Process environment
        # variables still have higher priority than either dotenv file.
        env_file=(ROOT_ENV_FILE, BACKEND_ENV_FILE),
        env_file_encoding="utf-8",
        env_prefix="APP_",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "AI Commerce Operations API"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    api_prefix: str = "/api/v1"
    web_origin: str = "http://127.0.0.1:3100"

    database_url: str = "sqlite:///./commerce_image.db"
    auto_create_tables: bool = True

    secret_key: SecretStr = Field(
        default_factory=lambda: SecretStr(secrets.token_urlsafe(48))
    )
    access_token_expire_minutes: int = 480
    seed_demo_data: bool = False
    demo_password: SecretStr | None = None

    image_provider: Literal["mock", "shulicode"] = "mock"
    image_api_base_url: str = Field(
        default="https://shulicode.xyz/v1",
        validation_alias=AliasChoices("APP_IMAGE_API_BASE_URL", "SHULICODE_BASE_URL"),
    )
    image_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("APP_IMAGE_API_KEY", "SHULICODE_API_KEY"),
    )
    image_model: str = Field(
        default="gpt-image-2",
        validation_alias=AliasChoices("APP_IMAGE_MODEL", "SHULICODE_IMAGE_MODEL"),
    )
    image_request_timeout_seconds: float = 120.0

    @field_validator("image_api_base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        return value.rstrip("/")

    @field_validator("access_token_expire_minutes")
    @classmethod
    def validate_expiry(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("access_token_expire_minutes must be positive")
        return value

    @property
    def database_backend(self) -> str:
        return self.database_url.split(":", 1)[0]

    @property
    def image_api_configured(self) -> bool:
        return self.image_provider == "mock" or self.image_api_key is not None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
