from functools import lru_cache
from typing import Literal

from pathlib import Path

from pydantic import HttpUrl, PositiveInt, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _patch_supabase_secret_key_headers() -> None:
    try:
        from supabase._sync.client import Client
    except Exception:
        return

    if getattr(Client, "_wb_factory_secret_key_patch", False):
        return

    original_get_auth_headers = Client._get_auth_headers

    def get_auth_headers(self, authorization: str | None = None) -> dict[str, str]:
        headers = original_get_auth_headers(self, authorization)
        if str(self.supabase_key).startswith("sb_secret_"):
            headers.pop("Authorization", None)
            headers["apikey"] = self.supabase_key
        return headers

    Client._get_auth_headers = get_auth_headers
    Client._wb_factory_secret_key_patch = True


_patch_supabase_secret_key_headers()


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
    supabase_secret_key: SecretStr | None = None
    supabase_service_role_key: SecretStr | None = None
    supabase_mpstats_table: str = "mpstats_collections"
    supabase_product_content_jobs_table: str = "product_content_jobs"
    supabase_product_content_actions_table: str = "product_content_actions"
    supabase_supplier_products_table: str = "supplier_products"
    supabase_product_analyses_table: str = "product_analyses"
    supabase_wb_card_mappings_table: str = "wb_card_mappings"
    supabase_wb_stock_snapshots_table: str = "wb_stock_snapshots"

    mpstats_base_url: HttpUrl = HttpUrl("https://mpstats.io")
    mpstats_login_url: HttpUrl = HttpUrl("https://mpstats.io/login")
    mpstats_search_url: HttpUrl = HttpUrl("https://mpstats.io/wb/search")
    mpstats_headless: bool = True
    mpstats_timeout_ms: PositiveInt = 30_000
    mpstats_storage_state_path: Path = Path("data/mpstats-state.json")
    mpstats_email: str | None = None
    mpstats_password: SecretStr | None = None
    mpstats_token: SecretStr | None = None
    mpstats_api_token: SecretStr | None = None

    aidentika_base_url: HttpUrl = HttpUrl("https://api.aidentika.com/api/v1/public")
    aidentika_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    wb_content_api_token: SecretStr | None = None
    wb_content_base_url: HttpUrl = HttpUrl("https://content-api.wildberries.ru")
    wb_api_token: SecretStr | None = None
    wb_prices_base_url: HttpUrl = HttpUrl("https://discounts-prices-api.wildberries.ru")
    wb_statistics_base_url: HttpUrl = HttpUrl("https://statistics-api.wildberries.ru")

    def model_post_init(self, __context: object) -> None:
        if self.supabase_secret_key:
            self.supabase_service_role_key = self.supabase_secret_key

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_api_secret)

    @property
    def supabase_api_secret(self) -> SecretStr | None:
        return self.supabase_secret_key or self.supabase_service_role_key

    @property
    def mpstats_login_configured(self) -> bool:
        return bool(self.mpstats_email and self.mpstats_password)

    @property
    def mpstats_api_configured(self) -> bool:
        return bool(self.mpstats_token or self.mpstats_api_token)

    @property
    def mpstats_api_secret(self) -> SecretStr | None:
        return self.mpstats_token or self.mpstats_api_token

    @property
    def aidentika_configured(self) -> bool:
        return bool(self.aidentika_api_key)

    @property
    def openai_configured(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def wb_content_configured(self) -> bool:
        return bool(self.wb_content_api_token)

    @property
    def wb_api_configured(self) -> bool:
        return bool(self.wb_api_token or self.wb_content_api_token)

    @property
    def wb_api_secret(self) -> SecretStr | None:
        return self.wb_api_token or self.wb_content_api_token


@lru_cache
def get_settings() -> Settings:
    return Settings()
