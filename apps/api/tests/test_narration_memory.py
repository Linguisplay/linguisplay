# -*- coding: utf-8 -*-
"""🧠 让角色记得「做过什么」, 不只是「说过什么」(2026-08-04)。

`history_for` 是喂给模型的【唯一】记忆入口 —— 逐字近史窗和滚动摘要都从它取料。
而它只收两类拍: 玩家拍 与 dialogue 拍。`type == "description"` 的引擎旁白整类丢弃。

生产实测: 252717 / 327791 = 77.1% 的正文是旁白 —— 也就是说玩家读到的四分之三内容,
在回合结束的一刻就永久蒸发。玩家记得你们一起淋了那场雨, 角色只记得当时说的三句台词。
这是「记不住」的头号根因; 而且补这一个洞等于修两层(窗口与摘要共用这个入口)。

认知边界照旧: 旁白也按 present_ids 过滤 —— 我没在场的那场雨, 我不该记得。
"""
from app.engine import runtime


def _beats():
    return [
        {"author": "player", "text": "我们去后巷躲雨吧", "present_ids": ["a", "b"]},
        {"type": "description", "author": "engine", "present_ids": ["a", "b"],
         "text": "雨砸下来的时候，阿珍把外套罩在你头顶，自己淋了个透。"},
        {"type": "dialogue", "speaker_name": "阿珍", "present_ids": ["a", "b"],
         "text": "走快点，别站着。"},
        # 只有 b 在场的一拍 —— a 不该记得
        {"type": "description", "author": "engine", "present_ids": ["b"],
         "text": "巷口的灯灭了一下，又亮起来。"},
    ]


def _texts(rows):
    return " ".join(r.get("content", "") for r in rows)


def test_narration_reaches_memory():
    """旁白必须进记忆 —— 否则角色只记得说过的话, 不记得发生过的事。"""
    got = _texts(runtime.history_for(_beats(), "a"))
    assert "外套罩在你头顶" in got, "旁白没进记忆 — 一起淋的那场雨蒸发了"


def test_dialogue_and_player_still_there():
    got = _texts(runtime.history_for(_beats(), "a"))
    assert "去后巷躲雨" in got and "走快点" in got


def test_narration_respects_the_witness_gate():
    """认知边界: 我不在场的那一拍旁白, 我不该记得。"""
    got_a = _texts(runtime.history_for(_beats(), "a"))
    got_b = _texts(runtime.history_for(_beats(), "b"))
    assert "巷口的灯" not in got_a, "串了 — 认知边界破在旁白上"
    assert "巷口的灯" in got_b


def test_narration_is_not_mistaken_for_speech():
    """旁白不能被当成某个角色说的话 —— 否则模型会以为那是台词, 学着写旁白当对白。"""
    rows = runtime.history_for(_beats(), "a")
    narr = [r for r in rows if "外套罩在你头顶" in r.get("content", "")]
    assert narr, "旁白丢了"
    assert not narr[0]["content"].startswith("阿珍："), "旁白被贴上了说话人前缀"


def test_engine_only_beats_do_not_break_the_shape():
    """空文本 / 缺字段的拍不许把整条链搞崩。"""
    odd = [{"type": "description", "author": "engine", "present_ids": None, "text": ""},
           {"type": "description", "author": "engine", "present_ids": None},
           {"type": "dialogue", "present_ids": None, "text": "喂"}]
    rows = runtime.history_for(odd, "a")
    assert all(r.get("content") for r in rows), "空拍混进了记忆"
