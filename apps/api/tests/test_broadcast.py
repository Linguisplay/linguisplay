"""No explicit target = the player addresses the whole room: every present character
may answer (the mock always answers). An explicit target = only that character."""

from app.engine import runtime

CONTENT = {
    "story": {
        "id": "st",
        "characters": [
            {"id": "c1", "name": "Mara", "is_lead": True, "persona_text": "a"},
            {"id": "c2", "name": "Ron", "is_lead": False, "persona_text": "b"},
            {"id": "c3", "name": "Liu", "is_lead": False, "persona_text": "c"},
        ],
        "acts": [{"index": 1, "title": "一", "events": []}],
    },
    "secrets": [],
}


def _dialogue_speakers(beats):
    return [b["speaker_name"] for b in beats if b.get("type") == "dialogue"]


def test_no_target_broadcasts_to_everyone():
    out = runtime.run_turn(CONTENT, runtime.default_state(), {"name": "我"},
                           "有没有人知道出口在哪", channel="say")
    speakers = _dialogue_speakers(out["beats"])
    # all three present characters answer (mock never stays silent)
    assert set(speakers) == {"Mara", "Ron", "Liu"}


def test_explicit_target_is_one_on_one():
    out = runtime.run_turn(CONTENT, runtime.default_state(), {"name": "我"},
                           "你还好吗", channel="say", target_character_id="c2")
    assert _dialogue_speakers(out["beats"]) == ["Ron"]


def test_think_is_narration_only_even_with_a_crowd():
    out = runtime.run_turn(CONTENT, runtime.default_state(), {"name": "我"},
                           "（这里人也太多了）", channel="think")
    assert _dialogue_speakers(out["beats"]) == []
    assert any(b.get("type") == "description" for b in out["beats"])


def test_broadcast_has_single_narration():
    # only the primary responder narrates; members contribute dialogue only
    out = runtime.run_turn(CONTENT, runtime.default_state(), {"name": "我"},
                           "我们得想办法", channel="say")
    narrations = [b for b in out["beats"] if b.get("type") == "description"]
    assert len(narrations) == 1
