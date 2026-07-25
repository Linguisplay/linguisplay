# -*- coding: utf-8 -*-
"""🎤 开场玩家先发言 (tuning.opening_player_first): 开场只亮相不开口 — 台词与
差事由头全免, 第一句对话必须来自玩家; 开关关着一切照旧。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from app.engine import runtime  # noqa: E402


def _story(player_first: bool, language: str = "zh"):
    return {"story": {
        "id": "s", "language": language, "opening": "雨夜。你到了铺子门口。",
        "characters": [
            {"id": "c1", "name": "阿珍", "is_lead": True, "opening_line": "新来的？",
             "examples": ["坐。", "喝口热的。"]},
            {"id": "c2", "name": "细辉", "examples": ["别惹事。"]}],
        "acts": [{"index": 1, "title": "一", "goal": "落脚"}],
        "tuning": ({"opening_player_first": 1} if player_first else {}),
    }, "secrets": []}


class SpyLLM:
    """记下开场生成收到的 prompt, 自己装聋 (走确定性兜底)。"""

    def __init__(self):
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return {}


def test_flag_off_cast_speaks_first():
    st = runtime.default_state()
    beats = runtime.build_opening(_story(False), st)
    assert any(b["type"] == "dialogue" for b in beats), "开关关着: 角色照常开口"


def test_flag_on_nobody_speaks_before_player():
    st = runtime.default_state()
    spy = SpyLLM()
    beats = runtime.build_opening(_story(True), st, llm=spy)
    assert beats, "开场演出还在, 只是没人开口"
    assert all(b["type"] != "dialogue" for b in beats), \
        "第一句对话必须来自玩家 — 开场不许出现任何 dialogue 拍"
    # 作者开场白仍一字不落上台
    assert any("雨夜" in (b.get("text") or "") for b in beats)
    # 开场生成收到了 player_first 信号 (提示词侧不再要台词/hook)
    assert any(p.get("player_first") is True for p in spy.prompts
               if p.get("intro_vignettes"))
    # 差事由头不派 (没人开过口, 凭空落账 = 幻影差事)
    assert not any(g.get("kind") == "errand" for g in st.get("goals") or [])
    # 建议照发, 两条, 指向「怎么开口」
    assert len(st.get("suggestions") or []) == 2


def test_flag_on_en_story_gets_english_suggestions():
    st = runtime.default_state()
    runtime.build_opening(_story(True, language="en"), st, llm=SpyLLM())
    sugg = st.get("suggestions") or []
    assert len(sugg) == 2 and all(s.isascii() for s in sugg)


def test_flag_off_prompt_says_player_first_false():
    st = runtime.default_state()
    spy = SpyLLM()
    runtime.build_opening(_story(False), st, llm=spy)
    assert any(p.get("player_first") is False for p in spy.prompts
               if p.get("intro_vignettes"))
