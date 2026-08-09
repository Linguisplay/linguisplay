# -*- coding: utf-8 -*-
"""💘 追求线走得完 —— 第四环从前没有调用点 (审计 2026-08-09)。

链条四环，前三环都接上了，第四环是断的：

    court_tick           心动过线 → stage = 1        ✅
    court_directive_for  这一拍该 TA 主动             ✅
    court_beat_book      戏演出来了 → beats + 1      ✅
    court_apply_response stage 推进 / 三振死心        ❌ 整个仓库零个调用点

于是 stage 只在第一环被设成 1，之后没有任何代码能加到 2。线上 5 个角色全部卡在
第 1 步，court.step / court.over / court.won 一次都没响过。六阶段、三振出局、
冷却曲线全都写好了，全都跑不到。

接法不新增申报字段：模型这一拍已经在报 rel_event 了，拿它映射就够。
"""
from app.engine import runtime as R


C = {"story": {"id": "s",
               "characters": [{"id": "a", "name": "甲"}],
               "acts": [{"index": 1, "title": "一"}],
               "locations": [{"id": "l1", "name": "旧巷", "detail": "x", "exits": []}]}}


def _st(stage=1, **kw):
    st = R.default_state()
    st["location_id"] = "l1"
    st.setdefault("char_sim", {})["a"] = {"court": {"stage": stage, "rebuffs": 0,
                                                    "last_day": -1, "beats": 0}}
    st.update(kw)
    return st


def _court(st):
    return st["char_sim"]["a"]["court"]


def test_a_warm_beat_moves_it_forward():
    st = _st()
    R.court_apply_response(C, st, "a", R.COURT_RESP["心动"])
    assert _court(st)["stage"] == 2, "接受了却没推进 —— 第四环还是断的"


def test_a_rebuff_is_counted_not_swallowed():
    st = _st()
    R.court_apply_response(C, st, "a", R.COURT_RESP["冒犯"])
    assert _court(st)["rebuffs"] == 1
    assert _court(st)["stage"] == 1, "被拒还往前走"


def test_three_rebuffs_end_it():
    st = _st()
    for _ in range(3):
        R.court_apply_response(C, st, "a", R.COURT_RESP["争执"])
    assert _court(st).get("dead"), "三振了还没死心"


def test_an_unmapped_event_does_not_advance_on_its_own():
    """和好没进映射表，走「回避」——原地，不许白捡一级。"""
    st = _st()
    R.court_apply_response(C, st, "a", R.COURT_RESP.get("和好", ""))
    assert _court(st)["stage"] == 1


def test_two_unanswered_beats_still_advance():
    """保底那条别改坏：殷勤两拍没被拒 = 默许。"""
    st = _st()
    _court(st)["beats"] = 2
    R.court_apply_response(C, st, "a", "")
    assert _court(st)["stage"] == 2


def test_it_stops_at_the_top():
    st = _st(stage=6)
    R.court_apply_response(C, st, "a", R.COURT_RESP["心动"])
    assert _court(st)["stage"] == 6, "冲过了第 6 步"


def test_the_mapping_only_uses_events_the_model_already_reports():
    """不新增申报字段 —— 映射表里的键必须都是已有的 rel_event。"""
    assert set(R.COURT_RESP) <= set(R._REL_EVENTS)
