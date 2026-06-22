from functools import lru_cache
from typing import Literal

from pathlib import Path

from pydantic import HttpUrl, PositiveInt, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "WB Optimization API"
    app_env: Literal["development", "test", "production"] = "development"
    app_host: str = "0.0.0.0"
    app_port: PositiveInt = 8000
    log_level: str = "INFO"

    supabase_url: HttpUrl | None = None
    supabase_service_role_key: SecretStr | None = None
    supabase_mpstats_table: str = "mpstats_collections"

    mpstats_base_url: HttpUrl = HttpUrl("https://mpstats.io")
    mpstats_login_url: HttpUrl = HttpUrl("https://mpstats.io/login")
    mpstats_search_url: HttpUrl = HttpUrl("https://mpstats.io/wb/search")
    mpstats_headless: bool = True
    mpstats_timeout_ms: PositiveInt = 30_000
    mpstats_storage_state_path: Path = Path("data/mpstats-state.json")
    mpstats_email: str | None = None
    mpstats_password: SecretStr | None = None

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    @property
    def mpstats_login_configured(self) -> bool:
        return bool(self.mpstats_email and self.mpstats_password)


@lru_cache
def get_settings() -> Settings:
    return Settings()
