# -*- coding: utf-8 -*-
"""💘 追求节拍的接线 (2026-08-04 实弹排雷):

runtime.py:10322 `court_dir = court_directive_for(...)` 是个【赋了值从来没人读】的
局部变量, 而该函数是「查询即消费」—— 在提示词构建期就写 last_day/beats/_court_confess。
今天因为 court_tick 全仓零调用、stage 恒空所以是哑弹; 一旦有人接上 court_tick, 它会
变成: 生成失败或守卫重写时, 那一整个游戏日的名额已经花掉、表白已经武装, 而玩家一个字
都没看到 —— 比不接更糟。

所以: 取数只读, 落账挪到戏真的演出来之后 (court_beat_book), 指令真的进提示词。
"""
from app.engine import runtime


CONTENT = {"story": {"characters": [
    {"id": "c1", "name": "阿珍", "love_style": "傲娇"},
]}}


def _staged(stage=1, **court):
    st = runtime.default_state()
    st["char_sim"] = {"c1": {"court": {"stage": stage, "beats": 0, "last_day": -1, **court}}}
    return st


def test_directive_is_read_only():
    """取节拍指令绝不许动账本 —— 戏还没演, 账不能先记。"""
    st = _staged()
    before = runtime.copy.deepcopy(st["char_sim"]["c1"]["court"]) \
        if hasattr(runtime, "copy") else dict(st["char_sim"]["c1"]["court"])
    d = runtime.court_directive_for(CONTENT, st, "c1")
    assert d and "追求节拍" in d
    assert st["char_sim"]["c1"]["court"] == before, "取数写了账 — 这就是那颗地雷"
    assert "_court_confess" not in st


def test_booking_consumes_the_day_and_advances_beats():
    st = _staged()
    runtime.court_beat_book(CONTENT, st, "c1")
    court = st["char_sim"]["c1"]["court"]
    assert court["beats"] == 1
    assert court["last_day"] == runtime._time_index(st) // 3
    # 落过账之后当天不再出第二拍
    assert runtime.court_directive_for(CONTENT, st, "c1") is None


def test_confession_arms_only_at_stage_six_and_only_on_booking():
    st = _staged(stage=6)
    runtime.court_directive_for(CONTENT, st, "c1")
    assert "_court_confess" not in st, "取数就武装表白 = 戏没演卡先弹"
    runtime.court_beat_book(CONTENT, st, "c1")
    assert st.get("_court_confess") == "c1"


def test_dead_or_done_courtship_never_speaks():
    for kw in ({"dead": True}, {"done": True}):
        st = _staged(**kw)
        assert runtime.court_directive_for(CONTENT, st, "c1") is None


def test_apply_choice_survives_an_unknown_kind():
    """抉择卡的 kind 引擎不认时, 不许抛 ValueError 把存档卡死 (点不动的死卡)。"""
    st = runtime.default_state()
    st["pending_choice"] = {"kind": "court", "ask": "他把话说到了明处",
                            "options": [{"id": "court_yes", "label": "我也是"}]}
    runtime.apply_choice(CONTENT, st, "court_yes")   # 不抛 = 通过
    assert not st.get("pending_choice"), "认不出的卡也要收走, 否则永远挂在那儿"
