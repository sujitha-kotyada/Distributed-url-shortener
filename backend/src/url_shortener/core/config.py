from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Distributed URL Shortener"
    environment: str = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    base_url: str = Field(
        default="http://localhost:8000",
        validation_alias=AliasChoices("BASE_URL", "URL_SHORTENER_BASE_URL"),
    )
    database_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DATABASE_URL", "URL_SHORTENER_DATABASE_URL"),
    )
    redis_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("REDIS_URL", "URL_SHORTENER_REDIS_URL"),
    )
    redis_cache_ttl_seconds: int = Field(
        default=300,
        ge=1,
        validation_alias=AliasChoices(
            "REDIS_CACHE_TTL_SECONDS",
            "URL_SHORTENER_REDIS_CACHE_TTL_SECONDS",
        ),
    )
    redis_socket_timeout_seconds: float = Field(
        default=0.5,
        gt=0,
        validation_alias=AliasChoices(
            "REDIS_SOCKET_TIMEOUT_SECONDS",
            "URL_SHORTENER_REDIS_SOCKET_TIMEOUT_SECONDS",
        ),
    )
    redis_socket_connect_timeout_seconds: float = Field(
        default=0.5,
        gt=0,
        validation_alias=AliasChoices(
            "REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS",
            "URL_SHORTENER_REDIS_SOCKET_CONNECT_TIMEOUT_SECONDS",
        ),
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="URL_SHORTENER_",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
