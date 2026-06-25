from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://linguisplay:linguisplay@localhost:5432/linguisplay"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "dev-change-me"
    jwt_algorithm: str = "HS256"
    session_days: int = 30
    cookie_name: str = "lp_session"
    cookie_secure: bool = False
    web_origin: str = "http://localhost:5173"

    # LLM. provider = "mock" (deterministic, default — keeps tests reproducible)
    # or "qwen" (DashScope OpenAI-compatible endpoint).
    llm_provider: str = "mock"
    llm_model: str = "qwen-max"
    dashscope_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
