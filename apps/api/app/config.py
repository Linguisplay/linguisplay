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
    deepseek_model: str = "deepseek-v4-flash"   # 旧名 deepseek-chat 2026-07-24 弃用

    # 智能增强: when set, character enrichment grounds itself in live web search
    # (Tavily) instead of the model's own knowledge.
    tavily_api_key: str = ""

    # 火山方舟 (Volcengine Ark): unlocks 字节 Seedream image models — pass a
    # "doubao-seedream-*" model name to generate_image and it routes here.
    ark_api_key: str = ""

    # 🎙 声音克隆: DashScope enrollment 只吃公网 URL, 样本经这个基址临时可达
    public_base_url: str = "http://106.54.1.82:8100"
    openai_api_key: str = ""   # GPT Image 生图 (2026-07-21 Yi 提供; 只进 .env 不进代码)

    # 🔔 Web Push (活世界 P3): keys unset = the whole layer degrades silently.
    # Quiet hours are Asia/Shanghai wall-clock; pushes are a knock on the window,
    # the message itself always lands in the 小手机 regardless.
    vapid_private_key: str = ""
    vapid_public_key: str = ""
    vapid_sub: str = "mailto:ops@linguisplay.app"
    push_quiet_start: int = 23
    push_quiet_end: int = 8

    # plan/render 双拍合同 (docs/plan-render.md): the primary speaker's turn runs as a fast
    # structured plan call + a streamed prose render instead of one overloaded call.
    # Default OFF; a story can override either way via tuning.plan_render (pilot switch).
    plan_render: bool = False

    # ▶ drive 防刷 (⚖️ 无点击不推进, Yi 2026-07-14): 观剧拍无玩家输入, 脚本空转可无人
    # 值守刷剧情刷账单 — 服务端强制两拍之间的最小间隔秒数 (DRIVE_MIN_SECONDS)
    drive_min_seconds: int = 5

    # 💸 每用户每日回合配额 (上线成本防线, 2026-08-18): 0 = 不设限 (开发默认)。
    # 上线时在 .env 设 DAILY_TURN_QUOTA=300 之类; 口径 = 北京时间当天该用户名下
    # 所有局的玩家拍 (author='player'), 超了 /play 429, 零点翻篇。
    daily_turn_quota: int = 0

    # Logic backstop: after the addressed character's turn is generated, a deterministic guard
    # verifies it against the live scene (no absent character walks in, no locked secret leaks)
    # and regenerates once if broken. On by default; set LOGIC_GUARD=0 to disable.
    logic_guard: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
