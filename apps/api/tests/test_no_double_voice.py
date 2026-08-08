# -*- coding: utf-8 -*-
"""🗣 一拍里同一个角色不许被写两次 (Yi 报障 2026-08-08:「角色老是重复自己」)。

生产实弹 (存档 c3754b39):

    seq 118~122  21:46:56.57~58   ← 同一毫秒, 是【一次】生成吐出来的五拍
                 蓝信一 / 阿娣 / 蓝信一 / 旁白 / 阿娣
    seq 123      21:46:59.856     ← 3.3 秒后, 阿娣又被单独叫起来说了一次

    122 阿娣：你条数计到咁尽，连人哋几时撤货都摸清⋯⋯
    123 阿娣：你计到咁尽，连人哋几时撤货都摸清⋯⋯      （相似度 0.99）

根因: 群戏里主答者一次就把整场多人对话写完了, 包括其他角色的台词。而引擎随后
【照旧】把那些角色当作「接话成员」再叫一遍 —— 同一个角色在一拍里有两个作者。

said_this_turn 已经把「别人这一拍说过什么」喂给了后面的人, 让它「接话别复读」。
但那是【求模型自觉】: 它看见自己的台词在里面, 于是换了个措辞又说一遍。
凡是靠自觉的地方都会漏 —— 这一条改成确定性的: 已经开过口的人, 这一拍不再叫。
"""
from app.engine import runtime


def test_a_character_who_already_spoke_is_not_called_again():
    said = [{"speaker": "蓝信一", "text": "我选星期三。"},
            {"speaker": "旁白", "text": "阿娣转身把火调小。"},
            {"speaker": "阿娣", "text": "你条数计到咁尽，连人哋几时撤货都摸清？"}]
    pool = [{"id": "a", "name": "阿娣"}, {"id": "b", "name": "肥九"}]
    left = runtime.drop_already_spoken(pool, said)
    assert [c["id"] for c in left] == ["b"], "刚说过话的人又被叫起来了"


def test_being_mentioned_is_not_speaking():
    """⚠️ 只在【旁白里被提到】不算开过口 —— 那样会把该说话的人也筛掉。"""
    said = [{"speaker": "旁白", "text": "阿娣转过身，看着他没说话。"}]
    pool = [{"id": "a", "name": "阿娣"}]
    assert len(runtime.drop_already_spoken(pool, said)) == 1


def test_an_empty_line_is_not_speaking():
    said = [{"speaker": "阿娣", "text": "  "}]
    pool = [{"id": "a", "name": "阿娣"}]
    assert len(runtime.drop_already_spoken(pool, said)) == 1


def test_nothing_said_yet_keeps_everyone():
    pool = [{"id": "a", "name": "阿娣"}, {"id": "b", "name": "肥九"}]
    assert runtime.drop_already_spoken(pool, []) == pool
    assert runtime.drop_already_spoken(pool, None) == pool


def test_it_never_empties_a_pool_it_should_not():
    """别把 bug 修成功能没了: 没人说过话的时候一个都不许筛掉。"""
    said = [{"speaker": "旁白", "text": "灶台上的汤滚了。"}]
    pool = [{"id": "a", "name": "阿娣"}]
    assert len(runtime.drop_already_spoken(pool, said)) == 1


# ── 整拍: 主答者替别人写了台词, 那个人就不该再被叫一次 ────────────────────────

CONTENT = {"story": {
    "id": "s",
    "characters": [{"id": "a", "name": "甲", "is_lead": True, "home_location_id": "l1"},
                   {"id": "b", "name": "乙", "home_location_id": "l1"}],
    "acts": [{"index": 1, "title": "一"}],
    "locations": [{"id": "l1", "name": "旧巷", "detail": "x", "exits": []}]}}


class _GroupLLM:
    """主答者一次写完整场多人对话 —— 生产里模型真的会这么干。"""

    def __init__(self):
        self.spoke_for = []

    def generate(self, prompt):
        if prompt.get("summarize"):
            return {"memory": ""}
        if prompt.get("suggest"):
            return {"suggestions": []}
        sp = prompt.get("speaker_name")
        if sp:
            self.spoke_for.append(sp)
        if sp == "甲":
            return {"beats": [{"type": "dialogue", "speaker_name": "甲", "text": "我先说。"},
                              {"type": "dialogue", "speaker_name": "乙", "text": "我也说一句。"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None,
                    "next_speakers": ["乙"]}
        return {"beats": [{"type": "dialogue", "speaker_name": sp, "text": "我也说一句啊。"}],
                "affinity_delta": 0, "advance_act": False, "ending": None}


def test_the_member_is_not_asked_again_after_the_primary_voiced_them():
    llm = _GroupLLM()
    st = runtime.default_state()
    st["location_id"] = "l1"
    st["act"] = 1
    out = runtime.run_turn(CONTENT, st, {"name": "我"}, "你们好", channel="say", llm=llm)
    lines = [(b.get("speaker_name"), b.get("text")) for b in out["beats"]
             if b.get("type") == "dialogue"]
    yi = [t for s, t in lines if s == "乙"]
    assert len(yi) <= 1, f"乙 在一拍里说了两次: {yi}"
