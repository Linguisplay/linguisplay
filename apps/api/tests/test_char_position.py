# -*- coding: utf-8 -*-
"""char_sim['pos'] is dual-written (location ids AND 场记 pose frames) — reading it
as a LOCATION must never leak the frame dict. Regression for the /map 500
(unhashable dict) hit by a playable character with no home_location_id."""
from app.engine import runtime

CONTENT = {"story": {
    "id": "cp",
    "characters": [{"id": "c1", "name": "记者", "playable": True, "persona_text": "a"}],
    "acts": [{"index": 1}],
    "locations": [
        {"id": "lA", "name": "病房", "detail": "d", "exits": ["走廊"]},
        {"id": "lB", "name": "走廊", "detail": "d", "exits": ["病房"]},
    ]}, "secrets": []}
CHAR = CONTENT["story"]["characters"][0]


def test_pose_frame_in_sim_pos_reads_as_its_at_location():
    st = {**runtime.default_state(), "location_id": "lA",
          "char_sim": {"c1": {"pos": {"text": "靠在门边", "at": "lB"}}}}
    assert runtime.char_position(CONTENT, st, CHAR) == "lB"
    # and the map view survives it (this exact shape 500'd /map in prod)
    m = runtime.map_view(CONTENT, st)
    assert any("记者" in n.get("chars", []) for n in m["nodes"] if n["id"] == "lB")


def test_booked_location_string_still_works():
    st = {**runtime.default_state(), "location_id": "lA",
          "char_sim": {"c1": {"pos": "lB"}}}
    assert runtime.char_position(CONTENT, st, CHAR) == "lB"


def test_garbage_pos_falls_back_to_first_location():
    st = {**runtime.default_state(), "location_id": "lA",
          "char_sim": {"c1": {"pos": {"text": "无记录"}}}}   # frame with no 'at'
    assert runtime.char_position(CONTENT, st, CHAR) == "lA"


def test_dying_pin_coerced_too():
    st = {**runtime.default_state(), "location_id": "lA",
          "char_sim": {"c1": {"hp": "dying", "pos": {"text": "倒在地上", "at": "lB"}}}}
    assert runtime.char_position(CONTENT, st, CHAR) == "lB"
