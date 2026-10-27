from functools import lru_cache
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EQUITYLENS_", env_file=".env", extra="ignore")
    database_url: str = "sqlite:///./data/equitylens.db"
    data_dir: Path = Path("./data")
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    demo: bool = False
    background_refresh: bool = True
    refresh_seconds: int = Field(3600, ge=900)
    history_cache_seconds: int = Field(1800, ge=60)
    fundamentals_cache_seconds: int = Field(21600, ge=300)
    api_token: str | None = None
    llm_api_key: str | None = Field(None, repr=False)
    llm_model: str = "gpt-4.1-mini"
    llm_base_url: str = "https://api.openai.com/v1"
    request_limit: int = Field(120, ge=1)
    sec_user_agent: str | None = None
    screener_auto_refresh: bool = False
    screener_refresh_seconds: int = Field(21600,ge=3600)
    screener_max_deep_analysis: int = Field(15,ge=1,le=50)
    screener_request_delay: float = Field(.5,ge=0,le=60)


@lru_cache
def get_settings() -> Settings:
    return Settings()
