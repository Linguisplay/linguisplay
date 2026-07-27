# -*- coding: utf-8 -*-
"""🚪 台词离场 (Yi: 角色「说」自己要走却走不了 — 之前只读旁白不读台词; 去处不明默认回家)。"""
from app.engine import runtime


def _content():
    return {"story": {"id": "s", "characters": [
        {"id": "a", "name": "蓝信一", "home_location_id": "l2"},
        {"id": "b", "name": "蔡妍", "home_location_id": "l2"}],
        "locations": [{"id": "l1", "name": "档口", "exits": ["l2"]},
                      {"id": "l2", "name": "凉茶铺", "exits": ["l1"]}]}, "secrets": []}


def _state():
    st = runtime.default_state()
    st["location_id"] = "l1"
    # 两人都 pin 在玩家所在地 l1 (在场)
    st["char_pins"] = {"a": "l1", "b": "l1"}
    return st


def test_dialogue_departure_now_books_exit():
    """角色台词说'我先走了' → 账本把 TA 挪走(回家 l2)。"""
    c, st = _content(), _state()
    beats = [{"type": "dialogue", "speaker_name": "蓝信一", "text": "行了，我先走了，铺子还有事。"}]
    out = runtime._settle_prose_exits(c, st, beats, pcid="p")
    assert "蓝信一" in out
    assert st["char_pins"]["a"] == "l2"          # 回家, 不是 AWAY
    assert st["char_pins"]["b"] == "l1"          # 没说走的人不动


def test_narration_exit_still_works():
    c, st = _content(), _state()
    beats = [{"type": "description", "text": "蔡妍说完，转身走了出去，头也不回。"}]
    out = runtime._settle_prose_exits(c, st, beats, pcid="p")
    assert "蔡妍" in out and st["char_pins"]["b"] == "l2"


def test_conditional_not_treated_as_exit():
    """'如果我走了' / '别走' 不算离场。"""
    c, st = _content(), _state()
    beats = [{"type": "dialogue", "speaker_name": "蓝信一", "text": "如果我走了，你怎么办？"},
             {"type": "dialogue", "speaker_name": "蔡妍", "text": "别走神，看着点货。"}]
    out = runtime._settle_prose_exits(c, st, beats, pcid="p")
    assert out == []
    assert st["char_pins"] == {"a": "l1", "b": "l1"}     # 都还在


def test_no_home_falls_back_away():
    c, st = _content(), _state()
    c["story"]["characters"][0]["home_location_id"] = ""     # 蓝信一没家
    beats = [{"type": "dialogue", "speaker_name": "蓝信一", "text": "我走了。"}]
    runtime._settle_prose_exits(c, st, beats, pcid="p")
    assert st["char_pins"]["a"] == runtime.AWAY


def test_following_char_released_on_exit():
    c, st = _content(), _state()
    st["following"] = ["a"]
    beats = [{"type": "dialogue", "speaker_name": "蓝信一", "text": "我先撤了。"}]
    runtime._settle_prose_exits(c, st, beats, pcid="p")
    assert "a" not in st["following"]
