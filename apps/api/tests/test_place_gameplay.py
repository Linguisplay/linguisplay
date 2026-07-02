"""Location as GAMEPLAY: location-gated fragments (be there to learn it), arrival
discovery, searchable props (现场物证), per-act character schedules, and the map view."""

from app.engine import gating, runtime

MAP = {
    "story": {
        "id": "st",
        "characters": [
            {"id": "c1", "name": "Mara", "is_lead": True, "home_location_id": "hall",
             "schedule": [{"from_act": 2, "location_id": "study"}]},
        ],
        "acts": [{"index": 1, "title": "一"}, {"index": 2, "title": "二"}],
        "locations": [
            {"id": "hall", "name": "门厅", "detail": "一盏吊灯", "exits": ["书房"]},
            {"id": "study", "name": "书房", "detail": "整墙的书架", "exits": ["门厅"],
             "props": [{"id": "p1", "name": "写字台抽屉", "fragment_id": "f_prop",
                        "detail": "抽屉锁着，钥匙孔有新鲜的划痕。"}]},
            {"id": "attic", "name": "阁楼", "detail": "落灰", "exits": [],
             "unlock": {"required_fragment_ids": ["f_loc"]}},
        ],
    },
    "secrets": [{
        "id": "s1", "character_id": "c1", "title": "书房的秘密",
        "fragments": [
            {"id": "f_loc", "content": "BODY_AT_STUDY", "retrieval_key": "k",
             "unlock": {"location_id": "study"}},
            {"id": "f_prop", "content": "BODY_IN_DRAWER", "retrieval_key": "k2",
             "unlock": {"affinity_min": 999}},
        ],
    }],
}


def test_location_gate_blocks_until_you_are_there():
    st = runtime.default_state()          # effective location = hall (first authored)
    frags = gating.iter_fragments(MAP)
    f = next(x for x in frags if x["id"] == "f_loc")
    st["location_id"] = "hall"
    assert not gating.fragment_unlocked(f, st)
    # one condition short (only the place) → NPC may hint, not hide
    assert gating.classify_guard(f, st) == "hint"
    st["location_id"] = "study"
    assert gating.fragment_unlocked(f, st)


def test_arrival_discovery_reveals_on_the_spot():
    st = {**runtime.default_state(), "location_id": "hall"}
    runtime.apply_move(MAP, st, "书房")
    found = runtime.discover_on_arrival(MAP, st)
    assert len(found) == 1 and "BODY_AT_STUDY" in found[0]["text"]
    assert "f_loc" in st["unlocked_fragment_ids"]
    # idempotent: coming back doesn't re-discover
    assert runtime.discover_on_arrival(MAP, st) == []


def test_prop_search_yields_evidence_once():
    st = {**runtime.default_state(), "location_id": "study"}
    # wrong channel → nothing; wrong place → nothing
    assert runtime.search_props(MAP, st, "翻翻写字台抽屉", channel="say") == []
    st2 = {**runtime.default_state(), "location_id": "hall"}
    assert runtime.search_props(MAP, st2, "翻翻写字台抽屉", channel="do") == []
    # right place + 做 channel + naming the prop → found (fragment attached)
    found = runtime.search_props(MAP, st, "我拉开写字台抽屉看看", channel="do")
    assert len(found) == 1 and found[0]["fragment_id"] == "f_prop"
    # once each: already-searched prop stays quiet
    assert runtime.search_props(MAP, st, "再翻一次写字台抽屉", channel="do") == []


def test_prop_search_unlocks_through_the_full_turn():
    st = {**runtime.default_state(), "location_id": "study"}
    out = runtime.run_turn(MAP, st, {"name": "我"}, "我拉开写字台抽屉", channel="do")
    assert "f_prop" in out["state"]["unlocked_fragment_ids"]  # despite affinity_min=999
    texts = " ".join(b.get("text", "") for b in out["beats"])
    assert "BODY_IN_DRAWER" in texts                          # narrated as physical evidence
    assert any(m["kind"] == "unlock" for m in out["moments"])  # celebrated


def test_schedule_moves_the_character_between_acts():
    assert runtime.char_home({"home_location_id": "hall"}, 1) == "hall"
    c = MAP["story"]["characters"][0]
    assert runtime.char_home(c, 1) == "hall"    # before from_act → home
    assert runtime.char_home(c, 2) == "study"   # schedule entry wins
    # scene membership follows: at hall in act2, Mara is NOT here anymore
    st = {**runtime.default_state(), "act": 2, "location_id": "hall"}
    assert runtime.scene_characters(MAP, st) == []
    st["location_id"] = "study"
    assert [c2["id"] for c2 in runtime.scene_characters(MAP, st)] == ["c1"]


def test_map_view_hides_locked_places_and_marks_position():
    st = {**runtime.default_state(), "location_id": "hall"}
    mv = runtime.map_view(MAP, st)
    names = [n["name"] for n in mv["nodes"]]
    assert "门厅" in names and "书房" in names
    assert "阁楼" not in names and mv["hidden"] == 1   # locked place = unnamed count only
    assert next(n for n in mv["nodes"] if n["name"] == "门厅")["here"] is True
    assert next(n for n in mv["nodes"] if n["name"] == "门厅")["chars"] == ["Mara"]
    # unlock the gating fragment → the attic surfaces on the map
    st["unlocked_fragment_ids"] = ["f_loc"]
    mv2 = runtime.map_view(MAP, st)
    assert "阁楼" in [n["name"] for n in mv2["nodes"]] and mv2["hidden"] == 0
