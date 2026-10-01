from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    port: int = 8000
    log_level: str = "INFO"
    web_concurrency: int = 1  # Jobs are in-memory; extra workers fork/lose preview state.

    default_account_name: str = "Account"
    data_dir: str = "./data"

    budgetbakers_api_base: str = "https://rest.budgetbakers.com/wallet/v1/api"
    budgetbakers_api_token: str = ""

    nbu_fx_lookback_days: int = 7
    max_upload_bytes: int = 15 * 1024 * 1024
    max_excel_rows: int = 20_000
    max_excel_uncompressed_bytes: int = 64 * 1024 * 1024
    max_wallet_pages: int = 50
    max_wallet_items: int = 10_000
    fingerprint_warn_count: int = 50_000


@lru_cache
def get_settings() -> Settings:
    return Settings()
