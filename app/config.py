from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    database_url: str = "postgresql+psycopg://kindred:kindred@localhost:5432/kindred"
    embed_dim: int = 16
    payment_timeout_trigger_cents: int = 999999
    introduction_min_confidence: float = Field(default=0.7, ge=0, le=1)
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"


settings = Settings()
