# -*- coding: utf-8 -*-
"""💞 好感事件记账制 (Yi 2026-07-25 定: 不许每句话打分, 关系由事写成):
模型只申报 {kind, evidence}, 分值/冷却查引擎法条; 闲聊=零变动; 正面事件按
(角色,类别) 冷却防刷, 负面零冷却; 剧本级 rel_events:0 可退回旧每句判。"""
from app.engine import runtime

STORY = {"story": {"id": "s", "tuning": {"turns_per_slot": 6},
                   "characters": [{"id": "a", "name": "阿珍", "is_lead": True,
                                   "relation_allowed": ["flirt", "lover"]},
                                  {"id": "b", "name": "细辉",
                                   "relation_allowed": ["peer", "friend"]}],
                   "acts": [{"index": 1, "title": "一"}]},
         "secrets": []}


class EventLLM:
    def __init__(self, rel_event=None):
        self.rel_event = rel_event
        self.prompts = []

    def generate(self, prompt):
        if prompt.get("intro") or prompt.get("observe") or prompt.get("suggest") \
                or prompt.get("risk_judge") or prompt.get("summarize") \
                or prompt.get("track_scene") or prompt.get("intro_vignettes") \
                or prompt.get("heart_digest"):
            return {}
        self.prompts.append(prompt)
        out = {"beats": [{"type": "dialogue", "speaker_name": prompt.get("speaker_name"),
                          "text": "嗯。"}],
               "affinity_delta": 3, "romance_delta": 2,   # 旧字段: 事件制下必须被无视
               "advance_act": False, "ending": None}
        if self.rel_event:
            out["rel_event"] = self.rel_event
        return out


def _turn(st, llm, text="随便聊聊"):
    return runtime.run_turn(STORY, st, {"name": "我"}, text, channel="say", llm=llm)["state"]


def test_smalltalk_moves_nothing():
    st = _turn(runtime.default_state(), EventLLM())
    sc = (st.get("rel") or {}).get("a") or {}
    assert int(sc.get("closeness", 5) or 5) == 5 and int(sc.get("romance", 0) or 0) == 0, \
        "没有事件: 旧的每句打分字段必须被无视, 关系纹丝不动"


def test_event_books_engine_lawful_delta():
    st = _turn(runtime.default_state(), EventLLM({"kind": "交心", "evidence": "她说了当年的事"}))
    sc = (st.get("rel") or {}).get("a") or {}
    assert int(sc.get("closeness", 0)) > 5, "交心事件按法条入账"


def test_positive_event_cooldown_blocks_farming():
    st = runtime.default_state()
    st = _turn(st, EventLLM({"kind": "交心", "evidence": "第一次"}))
    c1 = int(st["rel"]["a"]["closeness"])
    st = _turn(st, EventLLM({"kind": "交心", "evidence": "又来一次"}))
    assert int(st["rel"]["a"]["closeness"]) == c1, "冷却内同类事件 = 刷分驳回"


def test_negative_event_never_throttled():
    st = runtime.default_state()
    st = _turn(st, EventLLM({"kind": "冒犯", "evidence": "戳了痛处"}))
    c1 = int(st["rel"]["a"]["closeness"])
    st = _turn(st, EventLLM({"kind": "冒犯", "evidence": "又戳一次"}))
    assert int(st["rel"]["a"]["closeness"]) < c1, "负面事件零冷却, 伤害不限流"


def test_unknown_kind_rejected():
    st = _turn(runtime.default_state(), EventLLM({"kind": "抽象", "evidence": "x"}))
    sc = (st.get("rel") or {}).get("a") or {}
    assert int(sc.get("closeness", 5) or 5) == 5, "不在法条里的事件驳回"


def test_romance_event_needs_capable_char():
    st = _turn(runtime.default_state(), EventLLM({"kind": "心动", "evidence": "他笑了"}),
               text="细辉你看这个")
    # 主答者由引擎选角; 只要没有可恋角色吃到心动分即可
    sc_b = (st.get("rel") or {}).get("b") or {}
    assert int(sc_b.get("romance", 0) or 0) == 0, "不可恋角色不吃心动分"


def test_legacy_optout_keeps_per_line_scoring():
    story = {"story": {**STORY["story"], "tuning": {"turns_per_slot": 6, "rel_events": 0}},
             "secrets": []}
    st = runtime.run_turn(story, runtime.default_state(), {"name": "我"}, "聊聊",
                          channel="say", llm=EventLLM())["state"]
    sc = (st.get("rel") or {}).get("a") or {}
    assert int(sc.get("closeness", 0)) > 5, "rel_events:0 的剧本保留旧每句打分"


def test_prompt_carries_the_flag():
    llm = EventLLM()
    _turn(runtime.default_state(), llm)
    assert any(p.get("rel_events") is True for p in llm.prompts), \
        "契约旗要进提示词, 模型才知道该申报事件而不是打分"
