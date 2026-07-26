# -*- coding: utf-8 -*-
"""⏰ 现实对齐 (Yi 2026-07-26: 时间要和现实世界对齐, 角色也得知道才行):
生产默认 real_clock=1 — 故事时钟每回合校准到真实时刻, 四件套 (钟点/星期/日期/季节)
进 state.clock, 【现实时刻】行进角色提示词; 剧本级可关; 沙盒老合同不变。"""
from datetime import datetime

from app.engine import runtime

BASE = {"story": {"id": "s", "tuning": {"turns_per_slot": 6, "real_clock": 1},
                  "characters": [{"id": "a", "name": "阿珍", "is_lead": True}],
                  "acts": [{"index": 1, "title": "一"}]},
        "secrets": []}


class SpyLLM:
    def __init__(self):
        self.prompts = []

    def generate(self, prompt):
        if prompt.get("intro") or prompt.get("observe") or prompt.get("suggest") \
                or prompt.get("risk_judge") or prompt.get("summarize") \
                or prompt.get("track_scene") or prompt.get("intro_vignettes") \
                or prompt.get("heart_digest"):
            return {}
        self.prompts.append(prompt)
        return {"beats": [{"type": "dialogue", "speaker_name": prompt.get("speaker_name"),
                           "text": "嗯。"}],
                "affinity_delta": 0, "advance_act": False, "ending": None}


def test_clock_syncs_to_real_world_and_carries_facts():
    llm = SpyLLM()
    st = runtime.run_turn(BASE, runtime.default_state(), {"name": "我"}, "你好",
                          channel="say", llm=llm)["state"]
    c = st.get("clock") or {}
    now = datetime.now()
    assert c.get("real") and c.get("wd", "").startswith("星期") and c.get("date"), \
        "真实四件套要进时钟账本"
    want_slot = 0 if 5 <= now.hour < 12 else (1 if 12 <= now.hour < 18 else 2)
    assert c.get("slot") == want_slot, "slot 必须踩在真实钟点上"


def test_characters_are_told_the_real_time():
    llm = SpyLLM()
    runtime.run_turn(BASE, runtime.default_state(), {"name": "我"}, "现在几点了",
                     channel="say", llm=llm)
    assert any((p.get("real_now") or "").strip() for p in llm.prompts), \
        "【现实时刻】行必须进角色提示词 (角色也得知道才行)"


def test_optout_keeps_fictional_clock():
    story = {"story": {**BASE["story"], "tuning": {"turns_per_slot": 6, "real_clock": 0}},
             "secrets": []}
    st0 = runtime.default_state()
    st0["clock"] = {"day": 7, "slot": 1, "turns_in_slot": 0}
    llm = SpyLLM()
    st = runtime.run_turn(story, st0, {"name": "我"}, "你好", channel="say", llm=llm)["state"]
    assert (st.get("clock") or {}).get("day") == 7, "退出旗的剧本保留虚构时钟"
    assert not any((p.get("real_now") or "").strip() for p in llm.prompts)


def test_sandbox_explicit_off_still_respected():
    story = {"story": {**BASE["story"],
                       "sandbox": {"enabled": True, "real_time": False},
                       "tuning": {"turns_per_slot": 6, "real_clock": 1}},
             "secrets": []}
    assert runtime.real_time_on(story) is False, "沙盒显式关掉现实同步的老合同优先"
