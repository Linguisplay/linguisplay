# -*- coding: utf-8 -*-
"""🤫 读空气：两个人的戏，第三个人该闭嘴 (Yi 真人反馈 2026-08-08)。

存档 c3754b39 现场：

    蓝信一：星期三别穿制服来。码头的海风腥，沾上不好洗。
    玩家：（看了他一眼，便离开继续巡逻）
    蓝信一：（喉咙发紧，到嘴边的话全咽了回去）
    阿娣：望乜嘢望，人都转过街角啦。你星期三约边个啊？
    阿娣：睇渔船？⋯⋯忽然间约人去睇渔船，你话冇嘢？

那一刻是两个人的戏，第三个人被叫来插了两次话。

⚠️ 不是「默认所有人都接话」那种 bug —— next_speakers 是必填字段，模型【主动申报了】
阿娣该插嘴。从人物合理性上她确实会插：她是个爱管闲事的面档阿姨。
缺的是另一样：没人告诉模型【此刻这是你和 TA 两个人的戏】。字段描述只问「谁会自然地
接话」，那是在问【合理性】，不是在问【玩家此刻的投入在哪】。

所以给事实，不给禁令：引擎确定性地判出「二人时刻」，把它交给模型，由它自己决定。
"""
from app.engine import qwen, runtime


C = {"story": {
    "id": "s",
    "characters": [{"id": "a", "name": "甲", "is_lead": True},
                   {"id": "b", "name": "乙"}],
    "acts": [{"index": 1, "title": "一"}],
    "locations": [{"id": "l1", "name": "旧巷", "detail": "x", "exits": []}]}}


def _st(**kw):
    st = runtime.default_state()
    st["location_id"] = "l1"
    st.update(kw)
    return st


def _log(pairs):
    return [{"author": ("player" if s is None else "engine"),
             "type": "dialogue", "speaker_name": s, "text": t,
             "present_ids": ["a", "b"]} for s, t in pairs]


TWO = _log([(None, "你还好吗"), ("甲", "还行。"), (None, "真的？"), ("甲", "嗯。")])


def test_a_warm_two_person_scene_is_a_private_moment():
    st = _st(rel={"a": {"closeness": 60, "romance": 30, "trust": 50}})
    why = runtime.private_moment(C, st, "a", TWO)
    assert why, "两个人聊了半天、还有好感，这都不算二人时刻"


def test_a_cold_stranger_is_not():
    """别把所有场景都判成二人时刻 —— 那样全世界都不许说话了。"""
    st = _st(rel={"a": {"closeness": 2, "romance": 0, "trust": 5}})
    assert not runtime.private_moment(C, st, "a", TWO)


def test_a_scene_others_are_already_in_is_not_private():
    """刚才别人还在说话，那就不是二人独处。"""
    st = _st(rel={"a": {"closeness": 60, "romance": 30, "trust": 50}})
    busy = TWO + _log([("乙", "我说一句。")])
    assert not runtime.private_moment(C, st, "a", busy)


def test_no_history_no_claim():
    st = _st(rel={"a": {"closeness": 60, "romance": 30, "trust": 50}})
    assert not runtime.private_moment(C, st, "a", None)


# ── 提示词: 把它交给模型, 由它决定 ────────────────────────────────────────────

def _tool(**kw):
    p = {"speaker_name": "甲", "cast": ["甲", "乙"], "persona": {"name": "我"},
         "group_mode": "primary"}
    p.update(kw)
    return str(qwen._render_tool(p, "甲", False, "primary", "say", "x"))


def test_the_private_moment_reaches_the_field_that_picks_speakers():
    s = _tool(private_moment="你和 TA 正说到要紧处")
    assert "两个人" in s or "二人" in s, "选人的那个字段不知道此刻是二人时刻"
    assert "[]" in s, "没给它「谁都别接」这个明确出口"


def test_nothing_added_when_the_scene_is_not_private():
    """平时不许平白多一段 —— 每回合都在花 token。"""
    assert "两个人的戏" not in _tool()
