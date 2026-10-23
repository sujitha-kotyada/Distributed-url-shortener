import pytest
from url_shortener.core.config import Settings, get_settings


@pytest.fixture(autouse=True)
def isolate_settings_env_file(monkeypatch: pytest.MonkeyPatch):
    """Ensure tests run against clean in-memory settings without picking up root .env."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
