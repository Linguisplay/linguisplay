# -*- coding: utf-8 -*-
"""📟 主动找你 (Yi 2026-08-05: 让玩家感觉总是有人在找他)。

生产实况: 174 个存档里只有 5 个有过短信往来 —— 97% 的局角色一条消息都没发过。
根因不是管线缺(compose_message + phone_push 早就通用), 是【由头只有一个】:
唯一主动的产地 offline_pulse 只在「玩家离开又回来」那一拍开火, 而中位一局只有
4 个玩家回合, 中位玩家从来没有「回来」过。

Yi 点名的三个由头:
  ① 初次见面后一定要发消息自我介绍 —— 也正好补上「照面即给联系方式」造出的空手机
  ② 事件之后来一条总结性交流
  ③ 朋友圈要跟上

铁律: 主动是免费的、回应是昂贵的 —— 每条主动消息都不许把玩家逼进打字框,
所以名额闸 (PHONE_MAX_PER_TURN) 对新由头同样成立。
"""
import pytest

from app.engine import runtime


CONTENT = {"story": {
    "characters": [
        {"id": "a", "name": "阿彩", "is_lead": True, "persona_text": "银彩发廊的洗头妹",
         "eq_style": "嘴快心软", "home_location_id": "hall"},
        {"id": "b", "name": "十二少", "persona_text": "城寨四子之一",
         "eq_style": "吊儿郎当", "home_location_id": "hall"},
    ],
    "acts": [{"index": 1, "title": "一"}],
    "locations": [{"id": "hall", "name": "祥记面档"}],
    "phone": {"device": "手机"}}, "secrets": []}


class _LLM:
    """记下每一次 compose_msg 的由头, 让测试能断言「为什么发」。"""

    def __init__(self):
        self.reasons = []

    def generate(self, p):
        if p.get("compose_msg"):
            self.reasons.append(p.get("reason") or "")
            return {"msgs": ["刚认识，存个号。"]}
        if p.get("social_posts"):
            return {"posts": []}
        return {}


def _state(seen=("a", "b"), **kw):
    st = runtime.default_state()
    st["location_id"] = "hall"
    # phone.seen = 上次【面对面】的时刻。自我介绍认它不认 met_ids —— 账本上有名字
    # 不等于真打过照面 (开场/路过/旁白提及都会写 met_ids)。
    st.setdefault("phone", {}).setdefault("seen", {}).update({c: 1 for c in seen})
    st.update(kw)
    return st


def _msgs(st, cid):
    return (((st.get("phone") or {}).get("threads") or {}).get(cid) or {}).get("msgs") or []


# ── ① 初次见面就自我介绍 ────────────────────────────────────────────────────────

def test_first_meeting_earns_an_intro_text():
    # 照实际回合顺序来: 先照面入通讯录, 再发自我介绍 (没号的人不会给你发短信)。
    # 人要先离场 —— 当面聊着天手机响一声「你好我是阿彩」很蠢, 见 test_intro_waits_until_you_part。
    st = _state(met_ids=["a"], char_pins={"a": "elsewhere"})
    runtime.grant_contact_on_meet(CONTENT, st)
    llm = _LLM()
    runtime.reachout_on_meet(CONTENT, st, llm)
    assert _msgs(st, "a"), "见了面、拿了号, 手机却一条消息都没有 — 那是一部空机"
    assert any("初次" in r or "自我介绍" in r or "认识" in r for r in llm.reasons), \
        f"发消息的由头不对: {llm.reasons}"


def test_intro_fires_once_per_character():
    st = _state(met_ids=["a"], char_pins={"a": "elsewhere"})
    runtime.grant_contact_on_meet(CONTENT, st)
    llm = _LLM()
    runtime.reachout_on_meet(CONTENT, st, llm)
    n1 = len(_msgs(st, "a"))
    runtime.reachout_on_meet(CONTENT, st, llm)
    assert len(_msgs(st, "a")) == n1, "同一个人反复自我介绍 — 像坏掉的机器人"


def test_intro_respects_the_per_turn_cap():
    """一次见到一屋子人, 不许一口气弹一屏通知。"""
    st = _state(met_ids=["a", "b"], char_pins={"a": "x", "b": "y"})
    runtime.grant_contact_on_meet(CONTENT, st)
    llm = _LLM()
    runtime.reachout_on_meet(CONTENT, st, llm)
    total = len(_msgs(st, "a")) + len(_msgs(st, "b"))
    assert total <= runtime.PHONE_MAX_PER_TURN * 2, "一次见面炸出一屏消息"


def test_no_contact_no_text():
    """没拿到号的人不会给你发短信 (剧本可关照面即给)。"""
    c = {"story": dict(CONTENT["story"], tuning={"contact_on_meet": 0}), "secrets": []}
    st = _state(met_ids=["a"])
    runtime.reachout_on_meet(c, st, _LLM())
    assert not _msgs(st, "a")


def test_player_character_never_texts_themselves():
    st = _state(met_ids=["a"], player_character_id="a", char_pins={"a": "elsewhere"})
    runtime.grant_contact_on_meet(CONTENT, st)
    runtime.reachout_on_meet(CONTENT, st, _LLM())
    assert not _msgs(st, "a")


# ── ② 事件之后的总结性交流 ──────────────────────────────────────────────────────

def test_a_moment_earns_a_follow_up_text_after_parting():
    """刚一起经历了点什么, 【分开之后】来一条 —— 「他还在想那件事」最便宜的证明。

    当面不发: 你俩正站在一起, 手机响一声聊刚才的事很蠢。所以先押账, 等他离场那一拍送。"""
    st = _state(met_ids=["a"], contact_ids=["a"], char_pins={"a": "hall"})
    llm = _LLM()
    mo = [{"kind": "golden", "name": "阿彩", "title": "檐下躲雨"}]
    runtime.reachout_after_event(CONTENT, st, llm, mo)
    assert not _msgs(st, "a"), "人还在场就发短信聊刚才 — 当面的事当面说"
    assert (st.get("reach_owed") or {}).get("a") == "檐下躲雨", "没押账, 这条余温就丢了"
    st["char_pins"] = {"a": "elsewhere"}          # 他走了
    runtime.reachout_after_event(CONTENT, st, llm, [])
    assert _msgs(st, "a"), "他走了, 那条余温也没来"
    assert any("檐下躲雨" in r for r in llm.reasons), f"总结没带上那件事: {llm.reasons}"


def test_absent_character_does_not_summarize_what_they_missed():
    """认知边界: 没亲历的人永远不会来聊这件事 —— 连账都不该押。"""
    st = _state(met_ids=["a", "b"], contact_ids=["a", "b"],
                char_pins={"a": "hall", "b": "elsewhere"})
    llm = _LLM()
    runtime.reachout_after_event(CONTENT, st, llm,
                                 [{"kind": "golden", "name": "阿彩", "title": "檐下躲雨"}])
    assert not _msgs(st, "b"), "十二少没亲历, 却来聊这件事 — 认知边界破了"
    assert "b" not in (st.get("reach_owed") or {}), "给没在场的人押了账"


def test_no_moment_no_text():
    st = _state(met_ids=["a"], contact_ids=["a"], char_pins={"a": "elsewhere"})
    runtime.reachout_after_event(CONTENT, st, _LLM(), [])
    assert not _msgs(st, "a")


def test_intro_waits_until_you_part():
    """人还站在你面前时不发自我介绍 —— 当面聊着天手机响一声「你好我是阿彩」很蠢。"""
    st = _state(met_ids=["a"], char_pins={"a": "hall"})
    runtime.grant_contact_on_meet(CONTENT, st)
    runtime.reachout_on_meet(CONTENT, st, _LLM())
    assert not _msgs(st, "a"), "当面还发自我介绍短信"
    st["char_pins"] = {"a": "elsewhere"}
    runtime.reachout_on_meet(CONTENT, st, _LLM())
    assert _msgs(st, "a"), "分开之后那条自我介绍也没来"
