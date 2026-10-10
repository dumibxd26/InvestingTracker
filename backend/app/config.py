from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Northstar Wealth"
    database_url: str = "postgresql+psycopg://localhost/wealth_tracker"
    cors_origins: str = "http://localhost:5173"
    ai_model: str = ""
    chat_timeout_seconds: float = 25
    twelve_data_api_key: str = ""
    market_data_timeout_seconds: float = Field(default=10, ge=1, le=60)
    market_data_max_symbols: int = Field(default=50, ge=1, le=200)
    login_session_days: int = Field(default=30, ge=1, le=90)

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
