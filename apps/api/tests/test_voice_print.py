# -*- coding: utf-8 -*-
"""🗣 语言指纹 (情商军令③): 角色的说话规律进提示词宪章 — 数据侧强声线。"""
from app.engine import qwen, runtime


def test_voice_print_reaches_charter():
    sys = qwen._build_system({"speaker_name": "阿珍", "voice_print": "短句居多，句尾爱带「咯」",
                              "channel": "say"})
    assert "语言指纹" in sys and "句尾爱带「咯」" in sys


def test_no_print_no_block():
    sys = qwen._build_system({"speaker_name": "阿珍", "channel": "say"})
    assert "语言指纹" not in sys


def test_speaker_prompt_carries_it():
    story = {"story": {"id": "s", "tuning": {"turns_per_slot": 6},
                       "characters": [{"id": "a", "name": "阿珍", "is_lead": True,
                                       "voice_print": "从不说客套话"}],
                       "acts": [{"index": 1, "title": "一"}]}, "secrets": []}

    class Spy:
        def __init__(self): self.prompts = []
        def generate(self, prompt):
            if prompt.get("speaker_name"): self.prompts.append(prompt)
            return {"beats": [{"type": "dialogue", "speaker_name": "阿珍", "text": "嗯。"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}

    llm = Spy()
    runtime.run_turn(story, runtime.default_state(), {"name": "我"}, "你好",
                     channel="say", llm=llm)
    assert any(p.get("voice_print") == "从不说客套话" for p in llm.prompts)
