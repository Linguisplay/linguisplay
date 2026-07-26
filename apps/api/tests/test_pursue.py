# -*- coding: utf-8 -*-
"""💘 全员追玩家 (Yi: 所有角色都追玩家, 反向后宫): 行为层, 不碰 voice_print;
吊系地追 + 透过人设(第一诫)追; 默认关; 观剧拍不注入。"""
from app.engine import qwen, runtime


def test_pursue_charter_injected_when_on():
    sys = qwen._build_system({"speaker_name": "刃", "speaker_persona": "冷酷杀手",
                              "persona": {"name": "小满"}, "channel": "say", "context": {},
                              "pursue_player": True})
    assert "你对「小满」有意思" in sys
    assert "透过你自己的人设来追" in sys      # 人设优先, 不倒贴
    assert "绝不倒贴" in sys and "追而不逼" in sys


def test_no_pursue_when_off():
    sys = qwen._build_system({"speaker_name": "刃", "speaker_persona": "冷酷杀手",
                              "persona": {"name": "小满"}, "channel": "say", "context": {}})
    assert "有意思" not in sys


def test_pursue_never_in_observer_mode():
    sys = qwen._build_system({"speaker_name": "刃", "speaker_persona": "冷酷杀手",
                              "persona": {"name": "小满"}, "channel": "say", "context": {},
                              "observer": True, "pursue_player": True})
    assert "你对「小满」有意思" not in sys


def test_tuning_default_off_and_flag_reaches_prompt():
    assert runtime.DEFAULT_TUNING.get("pursue_player") == 0
    story = {"story": {"id": "s", "tuning": {"turns_per_slot": 6, "pursue_player": 1},
                       "characters": [{"id": "a", "name": "刃", "is_lead": True,
                                       "persona_text": "冷酷杀手"}],
                       "acts": [{"index": 1, "title": "一"}]}, "secrets": []}

    class Spy:
        def __init__(self): self.prompts = []
        def generate(self, prompt):
            if prompt.get("speaker_name"): self.prompts.append(prompt)
            return {"beats": [{"type": "dialogue", "speaker_name": "刃", "text": "嗯。"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}

    llm = Spy()
    runtime.run_turn(story, runtime.default_state(), {"name": "小满"}, "你好",
                     channel="say", llm=llm)
    assert any(p.get("pursue_player") for p in llm.prompts)
