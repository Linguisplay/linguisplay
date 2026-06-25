"""The 'think' channel is OBSERVE/EXAMINE: no target = look at the surroundings, a target
= examine that person. Narration only — no character speaks, no affinity change, and the
character's profile (not their secrets) drives a targeted look."""

from app.engine import runtime


CONTENT = {
    "story": {
        "id": "st",
        "characters": [{"id": "c1", "name": "Mara", "is_lead": True, "role": "向导"}],
        "acts": [{"index": 1, "title": "一", "events": []}],
    },
    "secrets": [],
}


def test_observe_surroundings_yields_narration_only():
    out = runtime.run_turn(CONTENT, runtime.default_state(), {"name": "我"},
                           "这是哪", channel="think")
    assert all(b.get("type") != "dialogue" for b in out["beats"])
    assert any(b.get("type") == "description" for b in out["beats"])
    assert out["state"]["affinity"] == 0


def test_examine_character_describes_that_person():
    out = runtime.run_turn(CONTENT, runtime.default_state(), {"name": "我"},
                           "看看她", channel="think", target_character_id="c1")
    text = " ".join(b.get("text", "") for b in out["beats"])
    assert "Mara" in text  # the examined person is described
    assert out["state"]["affinity"] == 0
    assert all(b.get("type") != "dialogue" for b in out["beats"])


def test_say_still_gets_dialogue():
    out = runtime.run_turn(CONTENT, runtime.default_state(), {"name": "我"},
                           "你好啊", channel="say")
    assert any(b.get("type") == "dialogue" for b in out["beats"])
