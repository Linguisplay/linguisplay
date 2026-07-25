# -*- coding: utf-8 -*-
"""📔 角色日记 (Yi 2026-07-25 定): 每日回忆结算是【整日总结】; 心动/甜蜜只住 TA 的
日记本 (暧昧/恋人档才解锁, 锁着只报条数不漏字), 普通标签留玩家回忆册。"""
from app.engine import relationships, runtime

STORY = {"story": {"id": "s", "tuning": {"turns_per_slot": 1},
                   "characters": [{"id": "a", "name": "阿珍", "is_lead": True,
                                   "relation_allowed": ["flirt", "lover"]}],
                   "acts": [{"index": 1, "title": "一"}]},
         "secrets": []}

HIST = [{"speaker": "a", "text": f"第{i}句闲聊"} for i in range(8)]


class DiaryLLM:
    def __init__(self, tag):
        self.tag = tag
        self.digest_prompts = []

    def generate(self, prompt):
        if prompt.get("heart_digest"):
            self.digest_prompts.append(prompt)
            return {"tag": self.tag, "title": "天台的风",
                    "text": "今天从早到晚都黏在一起，聊了店里的事也闹了笑话，"
                            "手机上还斗了几个来回的嘴，最后在天台吹了会风才散。",
                    "heart": "其实我想让风再大一点。" if self.tag in ("心动", "甜蜜") else ""}
        if prompt.get("intro") or prompt.get("observe") or prompt.get("suggest") \
                or prompt.get("risk_judge") or prompt.get("summarize") \
                or prompt.get("track_scene") or prompt.get("intro_vignettes"):
            return {}
        return {"beats": [{"type": "dialogue", "speaker_name": prompt.get("speaker_name"),
                           "text": "嗯。"}],
                "affinity_delta": 0, "advance_act": False, "ending": None}


def _new_day_turn(tag):
    st = runtime.default_state()
    st["clock"] = {"day": 1, "slot": 2, "turns_in_slot": 0}   # 夜: 这一回合翻天
    out = runtime.run_turn(STORY, st, {"name": "我"}, "晚安前再聊两句",
                           channel="say", llm=DiaryLLM(tag), history=HIST)
    return out["state"]


def test_heartbeat_day_goes_to_diary_not_album():
    st = _new_day_turn("心动")
    rows = (st.get("diaries") or {}).get("a") or []
    assert rows and rows[-1]["tag"] == "心动", "心动要进 TA 的日记"
    assert rows[-1]["heart"], "没说出口的那句要藏在日记里"
    assert not any(x.get("kind") == "daily" for x in (st.get("album") or [])), \
        "心动不再进玩家回忆册 (Yi 定: 搬家不是复制)"


def test_plain_day_stays_in_album():
    st = _new_day_turn("开心")
    assert not (st.get("diaries") or {}).get("a"), "普通标签不进日记"
    daily = [x for x in (st.get("album") or []) if x.get("kind") == "daily"]
    assert daily, "普通标签照旧进回忆册"


def test_diary_locked_until_flirt_tier():
    st = runtime.default_state()
    runtime._diary_add(st, "a", {"day": 1, "tag": "心动", "title": "x",
                                 "text": "整日总结", "heart": "z"})
    v = runtime.diary_view(STORY, st, "a")
    assert v["unlocked"] is False and v["count"] == 1 and v["entries"] == [], \
        "档位不够: 只报条数, 一个字不漏"
    st["rel"] = {"a": {**relationships.new_scores(), "romance": 40}}
    v2 = runtime.diary_view(STORY, st, "a")
    assert v2["unlocked"] is True and v2["entries"][-1]["text"] == "整日总结"


def test_diary_cap():
    st = runtime.default_state()
    for i in range(50):
        runtime._diary_add(st, "a", {"day": i, "tag": "心动", "title": "t",
                                     "text": str(i), "heart": ""})
    rows = st["diaries"]["a"]
    assert len(rows) == runtime._DIARY_CAP and rows[-1]["text"] == "49"


def test_profile_card_carries_diary_view():
    st = runtime.default_state()
    runtime._diary_add(st, "a", {"day": 1, "tag": "甜蜜", "title": "t",
                                 "text": "y", "heart": "h"})
    prof = runtime.character_profile(STORY, st, "a")
    assert prof and prof["diary"]["count"] == 1 and prof["diary"]["unlocked"] is False
