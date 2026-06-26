"""Physical-space anchoring: a story may author concrete `locations`; the run tracks which
place the player is in, feeds its concrete fixtures into the prompt, and lets the director
move the player ONLY along authored exits (an unknown destination is ignored, so the model
can't teleport or invent rooms). Stories without locations keep the old behavior (None)."""

from app.engine import runtime

MAP = {
    "story": {
        "id": "st",
        "characters": [{"id": "c1", "name": "Mara", "is_lead": True, "persona_text": "a"}],
        "acts": [{"index": 1, "title": "一"}],
        "locations": [
            {"id": "hall", "name": "门厅", "detail": "一盏吊灯，一张旧地毯", "exits": ["书房"]},
            {"id": "study", "name": "书房", "detail": "整墙的书架，一张写字台", "exits": ["门厅"]},
        ],
    },
    "secrets": [],
}

NOMAP = {
    "story": {"id": "s", "characters": [{"id": "c1", "name": "M", "is_lead": True}],
              "acts": [{"index": 1, "title": "a"}]},
    "secrets": [],
}


def test_current_location_defaults_to_first():
    st = runtime.default_state()
    assert st["location_id"] is None
    loc = runtime.current_location(MAP, st)
    assert loc and loc["id"] == "hall"  # unset → first authored place


def test_place_block_is_concrete_and_lists_exits():
    st = {**runtime.default_state(), "location_id": "study"}
    block = runtime._physical_place(MAP, st)
    assert "书房" in block and "整墙的书架" in block  # concrete fixtures present
    assert "门厅" in block                            # exit listed
    # no map → no place block at all
    assert runtime._physical_place(NOMAP, runtime.default_state()) == ""


def test_resolve_location_matches_name_or_id_else_none():
    assert runtime.resolve_location(MAP, "study")["id"] == "study"
    assert runtime.resolve_location(MAP, "书房")["id"] == "study"
    assert runtime.resolve_location(MAP, "你走进书房看了看")["id"] == "study"  # lenient contains
    assert runtime.resolve_location(MAP, "天台") is None                      # unknown → ignored


def test_director_move_applies_only_for_known_place():
    class MoverLLM:
        def __init__(self, dest):
            self.dest = dest

        def generate(self, prompt):
            if prompt.get("intro") or prompt.get("observe"):
                return {"beats": [{"type": "description", "speaker_name": None, "text": "x"}],
                        "affinity_delta": 0, "advance_act": False, "ending": None}
            return {"beats": [{"type": "dialogue", "speaker_name": prompt.get("speaker_name"), "text": "嗯"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None, "location": self.dest}

    # a recognized destination moves the player
    st = runtime.default_state()
    out = runtime.run_turn(MAP, st, {"name": "我"}, "去书房", channel="do", llm=MoverLLM("书房"))
    assert out["state"]["location_id"] == "study"
    assert out["location"]["id"] == "study"

    # an unknown destination is ignored — position unchanged
    st2 = {**runtime.default_state(), "location_id": "hall"}
    out2 = runtime.run_turn(MAP, st2, {"name": "我"}, "去天台", channel="do", llm=MoverLLM("天台"))
    assert out2["state"]["location_id"] == "hall"


def test_no_location_story_returns_none():
    out = runtime.run_turn(NOMAP, runtime.default_state(), {"name": "我"}, "你好", channel="say")
    assert out["location"] is None
