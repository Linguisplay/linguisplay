"""Run modes: 'character' (embody one of the cast — that character no longer answers as
an NPC) and 'god' (invisible observer — the cast interact with each other)."""

from app.engine import runtime

CONTENT = {
    "story": {
        "id": "st",
        "characters": [
            {"id": "c1", "name": "Mara", "is_lead": True, "persona_text": "a"},
            {"id": "c2", "name": "Ron", "persona_text": "b"},
            {"id": "c3", "name": "Liu", "persona_text": "c"},
        ],
        "acts": [{"index": 1, "title": "一", "events": []}],
    },
    "secrets": [],
}


def _speakers(beats):
    return {b["speaker_name"] for b in beats if b.get("type") == "dialogue"}


def test_character_mode_excludes_embodied_character():
    st = {**runtime.default_state(), "mode": "character", "player_character_id": "c1"}
    out = runtime.run_turn(CONTENT, st, {"name": "Mara"}, "大家怎么看", channel="say")
    spk = _speakers(out["beats"])
    assert "Mara" not in spk           # you ARE Mara — she doesn't answer as an NPC
    assert spk == {"Ron", "Liu"}
    assert all(c["id"] != "c1" for c in out["cast"])  # not addressable


def test_god_mode_cast_interacts_and_player_is_not_a_speaker():
    st = {**runtime.default_state(), "mode": "god"}
    out = runtime.run_turn(CONTENT, st, {"name": "我"}, "让他们聊聊过去", channel="say")
    spk = _speakers(out["beats"])
    # everyone present takes part; the player embodies no one
    assert spk == {"Mara", "Ron", "Liu"}


def test_god_mode_spotlight_target_leads():
    st = {**runtime.default_state(), "mode": "god"}
    out = runtime.run_turn(CONTENT, st, {"name": "我"}, "镜头给他", channel="say",
                           target_character_id="c2")
    # the spotlighted character narrates/leads; others may chime in
    dialogue = [b for b in out["beats"] if b.get("type") == "dialogue"]
    assert dialogue[0]["speaker_name"] == "Ron"
