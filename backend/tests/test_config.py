from __future__ import annotations

import pytest
from pydantic import ValidationError

from url_shortener.core.config import Settings, get_settings


def test_trusted_proxies_default_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRUSTED_PROXIES", raising=False)
    monkeypatch.delenv("URL_SHORTENER_TRUSTED_PROXIES", raising=False)
    get_settings.cache_clear()

    settings = Settings()
    assert settings.trusted_proxies == []


def test_trusted_proxies_empty_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTED_PROXIES", "")
    get_settings.cache_clear()

    settings = Settings()
    assert settings.trusted_proxies == []


def test_trusted_proxies_whitespace_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTED_PROXIES", "   \t \n ")
    get_settings.cache_clear()

    settings = Settings()
    assert settings.trusted_proxies == []


def test_trusted_proxies_json_single_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTED_PROXIES", '["127.0.0.1"]')
    get_settings.cache_clear()

    settings = Settings()
    assert settings.trusted_proxies == ["127.0.0.1"]


def test_trusted_proxies_json_multiple_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTED_PROXIES", '["127.0.0.1", "10.0.0.0/8", "192.168.1.0/24"]')
    get_settings.cache_clear()

    settings = Settings()
    assert settings.trusted_proxies == ["127.0.0.1", "10.0.0.0/8", "192.168.1.0/24"]


def test_trusted_proxies_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTED_PROXIES", "127.0.0.1, 10.0.0.0/8 , 172.16.0.0/12")
    get_settings.cache_clear()

    settings = Settings()
    assert settings.trusted_proxies == ["127.0.0.1", "10.0.0.0/8", "172.16.0.0/12"]


def test_trusted_proxies_json_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTED_PROXIES", "[]")
    get_settings.cache_clear()

    settings = Settings()
    assert settings.trusted_proxies == []


def test_trusted_proxies_malformed_json_like_input(monkeypatch: pytest.MonkeyPatch) -> None:
    # Bracketed input that fails JSON parsing must not be accepted or mangled
    monkeypatch.setenv("TRUSTED_PROXIES", "[127.0.0.1, missing_quote")
    get_settings.cache_clear()

    with pytest.raises(ValidationError, match="Malformed"):
        Settings()


def test_trusted_proxies_invalid_ip_cidr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRUSTED_PROXIES", "999.999.999.999")
    get_settings.cache_clear()

    with pytest.raises(ValidationError, match="Invalid IP or CIDR"):
        Settings()


def test_trusted_proxies_direct_python_list() -> None:
    settings = Settings(trusted_proxies=["10.0.0.1", "172.18.0.0/16"])
    assert settings.trusted_proxies == ["10.0.0.1", "172.18.0.0/16"]


def test_existing_settings_behavior_remains_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRUSTED_PROXIES", raising=False)
    monkeypatch.delenv("URL_SHORTENER_TRUSTED_PROXIES", raising=False)
    get_settings.cache_clear()

    settings = Settings()
    assert settings.app_name == "Distributed URL Shortener"
    assert settings.base_url == "http://localhost:8000"
    assert settings.redis_cache_ttl_seconds == 300
    assert settings.rate_limit_url_creation_per_minute == 20
    assert settings.rate_limit_redirect_per_minute == 100
    assert "http://localhost:3000" in settings.cors_origins


def test_trusted_proxies_field_type_is_strictly_list() -> None:
    settings = Settings()
    assert isinstance(settings.trusted_proxies, list)


def test_development_defaults_allow_dev_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("URL_SHORTENER_ENVIRONMENT", raising=False)
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("URL_SHORTENER_JWT_SECRET_KEY", raising=False)
    get_settings.cache_clear()

    settings = Settings()
    assert settings.environment == "development"
    assert "dev-insecure" in settings.jwt_secret_key


def test_production_rejects_default_development_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("URL_SHORTENER_JWT_SECRET_KEY", raising=False)
    get_settings.cache_clear()

    with pytest.raises(ValidationError, match="default development secret"):
        Settings()


def test_production_rejects_short_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "short-secret-less-than-32-chars")
    get_settings.cache_clear()

    with pytest.raises(ValidationError, match="at least 32 characters"):
        Settings()


def test_production_accepts_valid_strong_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    valid_key = "a" * 32
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", valid_key)
    get_settings.cache_clear()

    settings = Settings()
    assert settings.environment == "production"
    assert settings.jwt_secret_key == valid_key


def test_production_prefixed_environment_aliases_accept_strong_key_and_reject_dev_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Clear unprefixed variables to ensure only prefixed aliases are exercised
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

    # 1. Prefixed alias rejects default development secret
    monkeypatch.setenv("URL_SHORTENER_ENVIRONMENT", "production")
    monkeypatch.delenv("URL_SHORTENER_JWT_SECRET_KEY", raising=False)
    get_settings.cache_clear()

    with pytest.raises(ValidationError, match="default development secret"):
        Settings()

    # 2. Prefixed alias accepts valid strong secret
    valid_key = "b" * 32
    monkeypatch.setenv("URL_SHORTENER_JWT_SECRET_KEY", valid_key)
    get_settings.cache_clear()

    settings = Settings()
    assert settings.environment == "production"
    assert settings.jwt_secret_key == valid_key
