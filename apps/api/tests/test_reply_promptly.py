# -*- coding: utf-8 -*-
"""📱 没事就及时回 (Yi 2026-08-09:「可以耍脾气或有原因，但没事的话一定要及时回复」)。

线上分布: now 43 次 / 延迟 8 次。找下来最松的是这一条:

    if sim.intent 非空且没过期: return "later"      # 「应承了具体差事，手上有活」

而 self_intent 是模型【几乎每拍都会填】的字段（「我先去看看」「回头找他问问」）。
于是角色只要说过接下来要干什么，就变成不方便回消息 —— 可真人恰恰是边干活边回消息，
手机就是干这个用的。

留下来的延迟理由都是【真有事】: 死了 / 被掳走 / 作者班表说此刻联系不上 / 半夜在睡 /
此刻正赴另一个约 / 钉子 AWAY。手上有个打算不算事。
"""
from app.engine import runtime


C = {"story": {
    "id": "s",
    "characters": [{"id": "a", "name": "甲"}],
    "acts": [{"index": 1, "title": "一"}],
    "locations": [{"id": "l1", "name": "旧巷", "detail": "x", "exits": []}]}}
CH = C["story"]["characters"][0]


def _st(**kw):
    st = runtime.default_state()
    st["location_id"] = "l1"
    st["clock"] = {"day": 1, "slot": 1}
    st.update(kw)
    return st


def _tier(st, th=None):
    return runtime._phone_beat(C, st, CH, "在吗", False, th or {})[0]


def test_a_plan_is_not_a_reason_to_go_quiet():
    """⚠️ 这一条就是 Yi 报的那件事。"""
    st = _st(char_sim={"a": {"intent": "我先去码头问问四仔",
                             "intent_at": runtime._time_index(_st())}})
    assert _tier(st) == "now", "角色只是说了句接下来要干什么，就不回消息了"


def test_nothing_going_on_means_reply_now():
    assert _tier(_st()) == "now"


def test_a_real_appointment_still_delays():
    """真有事还是可以晚点回 —— 别把 bug 修成「永远秒回」，那也不像人。"""
    # ⚠️ 约定里的 slot 存的是【名字】(晨/午/夜)，而 state.clock.slot 存的是【索引】。
    #    两把尺，各用各的。这个坑今天已经踩过第二次了。
    st = _st(promises=[{"char_id": "a", "status": "open", "day": 1, "slot": "午",
                        "location_id": "l1", "what": "见面"}])
    assert _tier(st) != "now"


def test_the_dead_do_not_text_back():
    st = _st(char_sim={"a": {"hp": "dead"}})
    assert _tier(st) == "never"


def test_a_debt_on_the_thread_forces_a_reply():
    """线程上欠着债就得还 —— 这条原本就在，别改坏。"""
    st = _st()
    assert _tier(st, {"last_read": {"reason": "在气头上"}}) == "now"
