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


def test_director_move_is_a_confirmable_request_not_a_teleport():
    """The model can only PROPOSE a move (move_invite) — the player stays put until they
    confirm (apply_move, the /move endpoint). An off-map destination becomes an emergent
    generate-on-accept offer, never a silent teleport."""
    class MoverLLM:
        def __init__(self, dest):
            self.dest = dest

        def generate(self, prompt):
            if prompt.get("intro") or prompt.get("observe") or prompt.get("suggest"):
                return {"beats": [{"type": "description", "speaker_name": None, "text": "x"}],
                        "affinity_delta": 0, "advance_act": False, "ending": None}
            return {"beats": [{"type": "dialogue", "speaker_name": prompt.get("speaker_name"), "text": "嗯"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None, "move_invite": self.dest}

    # a known, connected destination → a confirm request; NOT moved yet
    st = runtime.default_state()
    out = runtime.run_turn(MAP, st, {"name": "我"}, "去书房", channel="do", llm=MoverLLM("书房"))
    assert out["state"]["location_id"] in (None, "hall")   # unmoved until the player confirms
    assert out["move_request"] and out["move_request"]["to"] == "study"
    # confirming actually moves
    dest = runtime.apply_move(MAP, out["state"], "书房")
    assert dest["id"] == "study" and out["state"]["location_id"] == "study"

    # an off-map destination → offered as an EMERGENT place (generate on accept), no teleport
    st2 = {**runtime.default_state(), "location_id": "hall"}
    out2 = runtime.run_turn(MAP, st2, {"name": "我"}, "去天台", channel="do", llm=MoverLLM("天台"))
    assert out2["state"]["location_id"] == "hall"
    assert out2["move_request"] and out2["move_request"].get("generate") is True
    assert out2["move_request"]["to"] is None and out2["move_request"]["to_name"] == "天台"


def test_no_location_story_returns_none():
    out = runtime.run_turn(NOMAP, runtime.default_state(), {"name": "我"}, "你好", channel="say")
    assert out["location"] is None


def test_depth_anchor_is_short_and_grounded():
    from app.engine import qwen
    place = runtime._physical_place(MAP, {**runtime.default_state(), "location_id": "study"})
    roster = "此刻这个场景里实际在场的人：我（你）、Mara——共 2 人。不要数错。"
    anchor = qwen._depth_anchor({"place": place, "roster": roster})
    assert "书房" in anchor          # the current place is restated near the user turn
    assert "共 2 人" in anchor        # and the deterministic headcount
    assert "\n" not in anchor         # it's a short one-liner, not the whole block
    # nothing physical → no anchor
    assert qwen._depth_anchor({}) == ""


def test_depth_anchor_pins_the_clock():
    from app.engine import qwen
    # ⏰ the current time rides at the generation point — characters must not call
    # a morning "下午" (real-time sandbox bug)
    a = qwen._depth_anchor({"clock": "第3天·晨 09:24"})
    assert "第3天·晨 09:24" in a and "不能说错时辰" in a
    b = qwen._depth_anchor({"clock": "Day 3 · Morning 09:24", "language": "en"})
    assert "Day 3 · Morning 09:24" in b and "must match" in b
