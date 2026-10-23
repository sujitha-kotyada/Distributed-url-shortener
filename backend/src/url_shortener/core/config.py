from functools import lru_cache
import ipaddress
import json
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Distributed URL Shortener"
    environment: str = Field(
        default="development",
        validation_alias=AliasChoices("ENVIRONMENT", "URL_SHORTENER_ENVIRONMENT"),
    )
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
    analytics_stream_name: str = Field(
        default="url_shortener:redirect_events",
        validation_alias=AliasChoices(
            "ANALYTICS_STREAM_NAME",
            "URL_SHORTENER_ANALYTICS_STREAM_NAME",
        ),
    )
    analytics_consumer_group: str = Field(
        default="url_shortener:redirect_analytics",
        validation_alias=AliasChoices(
            "ANALYTICS_CONSUMER_GROUP",
            "URL_SHORTENER_ANALYTICS_CONSUMER_GROUP",
        ),
    )
    analytics_consumer_name: str = Field(
        default="worker-1",
        validation_alias=AliasChoices(
            "ANALYTICS_CONSUMER_NAME",
            "URL_SHORTENER_ANALYTICS_CONSUMER_NAME",
        ),
    )
    analytics_read_block_ms: int = Field(
        default=1000,
        ge=100,
        le=60000,
        validation_alias=AliasChoices(
            "ANALYTICS_READ_BLOCK_MS",
            "URL_SHORTENER_ANALYTICS_READ_BLOCK_MS",
        ),
    )
    analytics_batch_size: int = Field(
        default=10,
        ge=1,
        le=1000,
        validation_alias=AliasChoices(
            "ANALYTICS_BATCH_SIZE",
            "URL_SHORTENER_ANALYTICS_BATCH_SIZE",
        ),
    )
    analytics_claim_idle_ms: int = Field(
        default=60000,
        ge=1000,
        validation_alias=AliasChoices(
            "ANALYTICS_CLAIM_IDLE_MS",
            "URL_SHORTENER_ANALYTICS_CLAIM_IDLE_MS",
        ),
    )
    analytics_stream_maxlen: int = Field(
        default=100000,
        ge=1000,
        validation_alias=AliasChoices(
            "ANALYTICS_STREAM_MAXLEN",
            "URL_SHORTENER_ANALYTICS_STREAM_MAXLEN",
        ),
    )
    analytics_dlq_stream_name: str = Field(
        default="url_shortener:redirect_events:dlq",
        validation_alias=AliasChoices(
            "ANALYTICS_DLQ_STREAM_NAME",
            "URL_SHORTENER_ANALYTICS_DLQ_STREAM_NAME",
        ),
    )
    analytics_max_retries: int = Field(
        default=3,
        ge=1,
        le=10,
        validation_alias=AliasChoices(
            "ANALYTICS_MAX_RETRIES",
            "URL_SHORTENER_ANALYTICS_MAX_RETRIES",
        ),
    )
    jwt_secret_key: str = Field(
        default="dev-insecure-jwt-secret-key-change-in-production-12345",
        validation_alias=AliasChoices(
            "JWT_SECRET_KEY",
            "URL_SHORTENER_JWT_SECRET_KEY",
        ),
    )
    jwt_algorithm: str = Field(
        default="HS256",
        validation_alias=AliasChoices(
            "JWT_ALGORITHM",
            "URL_SHORTENER_JWT_ALGORITHM",
        ),
    )
    jwt_access_token_expire_minutes: int = Field(
        default=60,
        ge=1,
        validation_alias=AliasChoices(
            "JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
            "URL_SHORTENER_JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
        ),
    )
    rate_limit_url_creation_per_minute: int = Field(
        default=20,
        ge=1,
        validation_alias=AliasChoices(
            "RATE_LIMIT_URL_CREATION_PER_MINUTE",
            "URL_SHORTENER_RATE_LIMIT_URL_CREATION_PER_MINUTE",
        ),
    )
    rate_limit_redirect_per_minute: int = Field(
        default=100,
        ge=1,
        validation_alias=AliasChoices(
            "RATE_LIMIT_REDIRECT_PER_MINUTE",
            "URL_SHORTENER_RATE_LIMIT_REDIRECT_PER_MINUTE",
        ),
    )
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://localhost:8000",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:8000",
        ],
        validation_alias=AliasChoices("CORS_ORIGINS", "URL_SHORTENER_CORS_ORIGINS"),
    )
    trusted_proxies: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        validation_alias=AliasChoices(
            "TRUSTED_PROXIES",
            "URL_SHORTENER_TRUSTED_PROXIES",
        ),
    )

    @field_validator("trusted_proxies", mode="before")
    @classmethod
    def validate_trusted_proxies(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                return []
            if cleaned.startswith("[") and cleaned.endswith("]"):
                try:
                    parsed = json.loads(cleaned)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Malformed JSON array in trusted_proxies: {exc}") from exc
                if not isinstance(parsed, list):
                    raise ValueError("trusted_proxies JSON must be an array of strings")
                items = parsed
            elif cleaned.startswith("[") or cleaned.endswith("]"):
                raise ValueError("Malformed bracketed JSON array in trusted_proxies")
            else:
                items = [item.strip() for item in cleaned.split(",") if item.strip()]
        elif isinstance(value, (list, tuple, set)):
            items = list(value)
        else:
            raise ValueError("trusted_proxies must be a list of IP or CIDR strings")

        result: list[str] = []
        for item in items:
            if not isinstance(item, str):
                raise ValueError(f"trusted_proxies entries must be strings, got {type(item).__name__}")
            item_str = item.strip()
            if not item_str:
                continue
            try:
                ipaddress.ip_network(item_str, strict=False)
            except ValueError as exc:
                raise ValueError(f"Invalid IP or CIDR address in trusted_proxies: {item_str!r}") from exc
            result.append(item_str)
        return result

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        if self.environment.strip().lower() == "production":
            dev_default = "dev-insecure-jwt-secret-key-change-in-production-12345"
            if self.jwt_secret_key == dev_default or "dev-insecure" in self.jwt_secret_key:
                raise ValueError(
                    "JWT_SECRET_KEY cannot use the default development secret in production."
                )
            if len(self.jwt_secret_key) < 32:
                raise ValueError(
                    "JWT_SECRET_KEY must be at least 32 characters long in production."
                )
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="URL_SHORTENER_",
        populate_by_name=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
