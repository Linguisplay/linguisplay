# -*- coding: utf-8 -*-
"""🎭 会露怯 (Yi: 治「角色永远占上风=下头」): 宪章常驻反完美话术锚 +
引擎每 4 拍给主答者一记 off_balance 放大。"""
from app.engine import qwen, runtime


def test_anti_dominance_anchor_always_present():
    sys = qwen._build_system({"speaker_name": "蓝信一", "speaker_persona": "城寨头马",
                              "persona": {"name": "你"}, "channel": "say", "context": {}})
    assert "永远占上风的完美话术机器" in sys      # 反完美话术锚常驻
    assert "输一手" in sys or "露怯" in sys


def test_off_balance_amplifier_when_set():
    sys = qwen._build_system({"speaker_name": "蓝信一", "speaker_persona": "头马",
                              "persona": {"name": "你"}, "channel": "say", "context": {},
                              "off_balance": True})
    assert "这一拍你明显处下风" in sys


def test_no_amplifier_when_unset():
    sys = qwen._build_system({"speaker_name": "蓝信一", "speaker_persona": "头马",
                              "persona": {"name": "你"}, "channel": "say", "context": {}})
    assert "这一拍你明显处下风" not in sys


def test_tuning_default_on():
    assert runtime.DEFAULT_TUNING.get("fallible") == 1


def test_off_balance_fires_on_cadence():
    """主答者每 4 拍(turn_seq%4==3)收到一记 off_balance。"""
    seen = []

    class Spy:
        def generate(self, prompt):
            if prompt.get("speaker_name") and prompt.get("persona"):
                seen.append(bool(prompt.get("off_balance")))
            return {"beats": [{"type": "dialogue", "speaker_name": "甲", "text": "嗯。"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}

    story = {"story": {"id": "s", "tuning": {"turns_per_slot": 6},
                       "characters": [{"id": "a", "name": "甲", "is_lead": True}],
                       "acts": [{"index": 1, "title": "一"}]}, "secrets": []}
    st = runtime.default_state()
    fired = []
    for _ in range(5):
        seen.clear()
        out = runtime.run_turn(story, st, {"name": "你"}, "hi", channel="say", llm=Spy())
        st = out["state"]
        fired.append(any(seen))
    assert any(fired)   # 5 拍里至少响一次
