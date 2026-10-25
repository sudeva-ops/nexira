import pytest

from app.core.config import Settings
from app.core.llm import StubLLM


def test_settings_keep_api_and_owner_dsns_separate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://nexira_api:x@db/nexira")
    monkeypatch.setenv("MIGRATIONS_DATABASE_URL", "postgresql+asyncpg://nexira_owner:x@db/nexira")
    settings = Settings(_env_file=None)
    assert "nexira_api" in settings.database_url
    assert settings.migrations_database_url is not None
    assert "nexira_owner" in settings.migrations_database_url
    assert settings.home_tz == "Asia/Dubai"


def test_api_dsn_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValueError, match="database_url"):
        Settings(_env_file=None)


def test_owner_dsn_is_optional_for_the_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://nexira_api:x@db/nexira")
    monkeypatch.delenv("MIGRATIONS_DATABASE_URL", raising=False)
    assert Settings(_env_file=None).migrations_database_url is None


async def test_stub_llm_is_deterministic() -> None:
    llm = StubLLM()
    assert await llm.complete("hi") == await llm.complete("hi") == "[stub] hi"


def test_an_unset_app_env_means_pilot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fails closed (Prompt 16): a forgotten APP_ENV never turns on the demo APIs."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://nexira_api:x@db/nexira")
    monkeypatch.delenv("APP_ENV", raising=False)
    assert Settings(_env_file=None).app_env == "pilot"
