from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Northstar Wealth"
    database_url: str = (
        "postgresql+psycopg://wealth_dev:local-dev-only@localhost:5432/wealth_tracker"
    )
    cors_origins: str = "http://localhost:5173"
    seed_demo_data: bool = True
    demo_user_id: str = "95c9d74b-24aa-4c82-b13c-3fc45412c5c6"
    ai_model: str = "gpt-4o-mini"
    chat_timeout_seconds: float = 25

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
