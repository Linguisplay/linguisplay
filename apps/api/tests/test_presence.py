"""Offstage characters (ghosts / absent people) are never live participants, and a
character with appears_from_act only joins the scene from that act onward."""

from app.engine import runtime

CONTENT = {
    "story": {
        "id": "st",
        "characters": [
            {"id": "lead", "name": "Mara", "is_lead": True, "persona_text": "a"},
            {"id": "buddy", "name": "Ron", "persona_text": "b"},
            {"id": "ghost", "name": "The Shape", "persona_text": "?", "presence": "offstage"},
            {"id": "latecomer", "name": "Vee", "persona_text": "c", "appears_from_act": 3},
        ],
        "acts": [{"index": 1, "title": "一", "events": []},
                 {"index": 2, "title": "二", "events": []},
                 {"index": 3, "title": "三", "events": []}],
    },
    "secrets": [],
}


def _speakers(beats):
    return {b["speaker_name"] for b in beats if b.get("type") == "dialogue"}


def test_offstage_ghost_never_answers_broadcast():
    out = runtime.run_turn(CONTENT, {**runtime.default_state(), "act": 1},
                           {"name": "我"}, "有人在吗", channel="say")
    spk = _speakers(out["beats"])
    assert "The Shape" not in spk
    assert "Mara" in spk and "Ron" in spk


def test_latecomer_absent_before_their_act():
    out = runtime.run_turn(CONTENT, {**runtime.default_state(), "act": 1},
                           {"name": "我"}, "都说说吧", channel="say")
    assert "Vee" not in _speakers(out["beats"])


def test_latecomer_present_from_their_act():
    out = runtime.run_turn(CONTENT, {**runtime.default_state(), "act": 3, "affinity": 40},
                           {"name": "我"}, "都说说吧", channel="say")
    assert "Vee" in _speakers(out["beats"])
    assert "The Shape" not in _speakers(out["beats"])  # ghost still never speaks


def test_cast_for_reflects_presence():
    names1 = {c["name"] for c in runtime.cast_for(CONTENT, 1)}
    names3 = {c["name"] for c in runtime.cast_for(CONTENT, 3)}
    assert names1 == {"Mara", "Ron"}
    assert names3 == {"Mara", "Ron", "Vee"}
    assert "The Shape" not in names1 | names3
