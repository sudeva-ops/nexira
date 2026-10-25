"""Runtime configuration, read from the environment (and .env for local runs).

Every key here is listed in the repository's .env.example.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    app_env: Literal["local", "demo", "test", "pilot"] = "local"

    # D-01: the API connects as nexira_api only; migrations run as nexira_owner.
    # The owner DSN is only given to the migrate job, never to the API container.
    database_url: str = Field(description="postgresql+asyncpg DSN for nexira_api")
    migrations_database_url: str | None = Field(
        default=None, description="postgresql+asyncpg DSN for nexira_owner (migrations only)"
    )

    redis_url: str = "redis://localhost:6379/0"

    # D-04 / plan G-04: the issuer is pinned; JWKS is fetched over the internal network.
    oidc_issuer: str = "http://localhost:8080/realms/nexira-demo"
    oidc_jwks_url: str = "http://localhost:8080/realms/nexira-demo/protocol/openid-connect/certs"
    oidc_audience: str = "nexira-api"

    home_tz: str = "Asia/Dubai"  # GST, UTC+4 (plan Q2)

    # app/core/llm.py: local gateway only, stub in tests (AGT-09).
    llm_provider: Literal["stub", "openai_compatible"] = "stub"
    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "llama3.1:8b"

    worker_tenant_ids: list[str] = Field(default_factory=list)  # plan G-01
    undo_window_s: int = 300  # plan G-17
    playbook_step_delay_s: float = 0.0  # demo pacing between playbook steps


@lru_cache
def get_settings() -> Settings:
    return Settings()  # required DSNs come from the environment
