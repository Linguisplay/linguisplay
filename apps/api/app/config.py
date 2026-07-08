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

    # LLM. provider = "mock" (deterministic, default — keeps tests reproducible),
    # "qwen" (DashScope OpenAI-compatible endpoint), or "deepseek" (api.deepseek.com,
    # OpenAI-compatible — cheaper + stronger prose/台词, the primary provider).
    llm_provider: str = "mock"
    llm_model: str = "qwen-max"
    dashscope_api_key: str = ""
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-chat"

    # 智能增强: when set, character enrichment grounds itself in live web search
    # (Tavily) instead of the model's own knowledge.
    tavily_api_key: str = ""

    # plan/render 双拍合同 (docs/plan-render.md): the primary speaker's turn runs as a fast
    # structured plan call + a streamed prose render instead of one overloaded call.
    # Default OFF; a story can override either way via tuning.plan_render (pilot switch).
    plan_render: bool = False

    # Logic backstop: after the addressed character's turn is generated, a deterministic guard
    # verifies it against the live scene (no absent character walks in, no locked secret leaks)
    # and regenerates once if broken. On by default; set LOGIC_GUARD=0 to disable.
    logic_guard: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
