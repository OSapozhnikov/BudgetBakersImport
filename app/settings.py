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
    web_concurrency: int = 1

    default_account_name: str = "Account"
    data_dir: str = "./data"

    budgetbakers_api_base: str = "https://api.budgetbakers.com/api/v1"
    budgetbakers_api_token: str = ""

    nbu_fx_lookback_days: int = 7
    preview_row_limit: int = 50


@lru_cache
def get_settings() -> Settings:
    return Settings()
