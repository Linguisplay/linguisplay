# -*- coding: utf-8 -*-
"""🧩 已知事实边界 (治「角色现编不该知道的私事」如周三休假) + 话别说满(台词留一手)。"""
from app.engine import qwen, runtime


def test_knowledge_boundary_always_present():
    sys = qwen._build_system({"speaker_name": "蓝信一", "speaker_persona": "头马",
                              "persona": {"name": "阿妍"}, "channel": "say", "context": {}})
    assert "你知道什么，有边界" in sys
    assert "亲口告诉过你" in sys and "一概" in sys      # 只认对话+授权, 别的不知道


def test_known_facts_injected_when_set():
    sys = qwen._build_system({"speaker_name": "蓝信一", "speaker_persona": "头马",
                              "persona": {"name": "阿妍"}, "channel": "say", "context": {},
                              "known_facts": "知道阿妍是新调来的实习警员"})
    assert "【你确知】：知道阿妍是新调来的实习警员" in sys


def test_no_known_facts_block_when_unset():
    sys = qwen._build_system({"speaker_name": "蓝信一", "speaker_persona": "头马",
                              "persona": {"name": "阿妍"}, "channel": "say", "context": {}})
    assert "【你确知】：" not in sys      # 注入体(带全角冒号)不出现; 规则文里的「【你确知】里」不算


def test_hold_back_anchor_present():
    sys = qwen._build_system({"speaker_name": "蓝信一", "speaker_persona": "头马",
                              "persona": {"name": "阿妍"}, "channel": "say", "context": {}})
    assert "话别说满，心别掏空" in sys       # 台词留一手 (C 的零延迟版)


def test_known_facts_reaches_prompt():
    story = {"story": {"id": "s", "tuning": {"turns_per_slot": 6},
                       "characters": [{"id": "a", "name": "蓝信一", "is_lead": True,
                                       "known_facts": "知道阿妍是新来的"}],
                       "acts": [{"index": 1, "title": "一"}]}, "secrets": []}

    class Spy:
        def __init__(self): self.p = []
        def generate(self, prompt):
            if prompt.get("speaker_name"): self.p.append(prompt)
            return {"beats": [{"type": "dialogue", "speaker_name": "蓝信一", "text": "嗯。"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}

    llm = Spy()
    runtime.run_turn(story, runtime.default_state(), {"name": "阿妍"}, "你好", channel="say", llm=llm)
    assert any(p.get("known_facts") == "知道阿妍是新来的" for p in llm.p)
