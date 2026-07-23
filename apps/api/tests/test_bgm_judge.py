# -*- coding: utf-8 -*-
"""🎼 乐师 (Yi 2026-07-22: 「bgm太差了」→ 高精度观察情绪 LLM 选曲):
判官读实际剧情文字选曲, 跑在关键路径外; 引擎报审 (白名单) + 迟滞 (无转折稳两回合);
硬状态 (亲热/危机) 仍由引擎压轴; 判官失灵回落九宫格规则。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from app.engine import director, runtime  # noqa: E402


def test_settle_music_whitelist_and_hysteresis():
    st = {}
    # 野曲名 → 报审驳回, 账本不动
    out = runtime.settle_music(st, {"track": "抖音神曲", "pivot": 2})
    assert out["track"] == "" and st["bgm_led"]["track"] == ""
    # 首次选曲 (held 0, pivot 0): 当前无曲 → track != led 且 held<2 且 pivot 0 → 不切?
    # 空档期不该沉默: 从无到有视作转折
    runtime.settle_music(st, {"track": "mystery", "pivot": 1})
    assert st["bgm_led"]["track"] == "mystery"
    # 无转折 + 刚切过 (held 1) → 迟滞挡住
    runtime.settle_music(st, {"track": "daily", "pivot": 0})
    assert st["bgm_led"]["track"] == "mystery"
    # 急转 → 立刻切
    runtime.settle_music(st, {"track": "battle", "pivot": 2})
    assert st["bgm_led"]["track"] == "battle"
    # 稳两回合后, 无转折也可换
    runtime.settle_music(st, {"track": "", "pivot": 0})
    runtime.settle_music(st, {"track": "", "pivot": 0})
    runtime.settle_music(st, {"track": "sad", "pivot": 0})
    assert st["bgm_led"]["track"] == "sad"


def test_stage_turn_judge_overrides_rules_but_not_hard_states():
    base_final = {"scene": {"mood": "日常"}, "state": {}, "music": {"track": "lonely"}}
    # 乐师判词压过九宫格
    assert director.stage_turn(base_final)["bgm"].startswith("lonely")
    # 野判词 → 回落规则
    junk = {"scene": {"mood": "日常"}, "state": {}, "music": {"track": "垃圾"}}
    assert director.stage_turn(junk)["bgm"].startswith("daily")
    # 床笫硬状态不容改判
    hot = {"scene": {"mood": "日常"}, "state": {"heat": {"stage": 2}},
           "music": {"track": "lonely"}}
    assert director.stage_turn(hot)["bgm"].startswith("romantic")


def test_turn_carries_music_verdict():
    story = {"story": {"id": "s", "characters": [{"id": "a", "name": "甲", "is_lead": True}],
                       "acts": [{"index": 1, "title": "一"}],
                       "locations": [{"id": "hall", "name": "门厅", "detail": "x",
                                      "exits": []}]},
             "secrets": []}

    class MoodyLLM:
        def generate(self, prompt):
            if prompt.get("music_judge"):
                # 判官收到的是这一回合的实际文字 + 曲库菜单
                assert "甲" in prompt.get("text", "") and prompt.get("menu")
                return {"track": "eerie", "pivot": 2, "feel": "背后发凉"}
            return {"beats": [
                {"type": "dialogue", "speaker_name": "甲", "text": "别回头。"},
            ], "affinity_delta": 0, "advance_act": False, "ending": None}

    out = runtime.run_turn(story, runtime.default_state(), {"name": "我"}, "怎么了",
                           channel="say", llm=MoodyLLM())
    assert out["music"] == {"track": "eerie", "feel": "背后发凉"}
    assert out["state"]["bgm_led"]["track"] == "eerie"
