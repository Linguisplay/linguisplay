# -*- coding: utf-8 -*-
"""🎀 VN (galgame) mode: a numeric tuning knob any authored story can flip; the
suggestion contract learns it so the choices become the interaction."""
from app.engine import runtime


def test_vn_mode_is_a_tuning_knob():
    off = {"story": {"id": "a", "tuning": {}}}
    on = {"story": {"id": "b", "tuning": {"vn_mode": 1}}}
    assert runtime.tuning_for(off)["vn_mode"] == 0
    assert runtime.tuning_for(on)["vn_mode"] == 1
