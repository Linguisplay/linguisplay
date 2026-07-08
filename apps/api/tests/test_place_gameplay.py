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


# ── 🤲 受赠确定性化: accepting an offered thing books it, no judgment field needed ──

def _accept_state():
    st = runtime.default_state()
    st["location_id"] = "hall"
    return st

_OFFER_HIST = [{"role": "assistant", "content": "老格伦：拿着，这把短刃跟了我三年，钢火没得挑。"}]


def test_accept_books_an_item_spoken_of_in_conversation():
    st = _accept_state()
    got = runtime.accept_item(MAP, st, "把短刃收入背包", "say", _OFFER_HIST)
    assert [i["name"] for i in got] == ["短刃"]
    assert runtime._inv_find(st["inventory"], "短刃") >= 0
    # accepting again is a no-op (already carried)
    assert runtime.accept_item(MAP, st, "收下短刃", "say", _OFFER_HIST) == []


def test_accept_refuses_items_never_seen_in_the_world():
    st = _accept_state()
    assert runtime.accept_item(MAP, st, "收下光之神剑", "say", _OFFER_HIST) == []
    assert not st.get("inventory")


def test_accept_takes_the_real_object_off_a_present_character():
    st = _accept_state()
    runtime.char_items(MAP, st, "c1").append({"name": "铜钥匙", "detail": "旧的"})
    got = runtime.accept_item(MAP, st, "接过铜钥匙", "say", [])
    assert [i["name"] for i in got] == ["铜钥匙"]
    assert runtime._inv_find(runtime.char_items(MAP, st, "c1"), "铜钥匙") < 0
    assert st["inventory"][0].get("detail") == "旧的"


def test_accept_never_fires_on_giving_away_or_english_smalltalk():
    st = _accept_state()
    st["inventory"] = [{"name": "短刃"}]
    assert runtime.accept_item(MAP, st, "把短刃递给他，让他收好", "say", _OFFER_HIST) == []
    hist_en = [{"role": "assistant", "content": "Glen: Take the dagger, it's yours."}]
    got = runtime.accept_item(MAP, {**_accept_state()}, "I accept the dagger.", "say", hist_en)
    assert [i["name"] for i in got] == ["dagger"]
    assert runtime.accept_item(MAP, _accept_state(), "let me take a look around", "say", hist_en) == []


# ── 🚶 说走就走: a first-person "go to X" executes deterministically ──

def test_player_move_walks_to_a_named_exit():
    st = {**runtime.default_state(), "location_id": "hall"}
    dest = runtime.player_move(MAP, st, "我们去书房看看", "say")
    assert dest and dest["id"] == "study" and st["location_id"] == "study"
    # partial name resolves too (「回门厅」 vs authored 门厅)
    dest = runtime.player_move(MAP, st, "回门厅", "do")
    assert dest and dest["id"] == "hall"


def test_player_move_multi_hop_routes_through_unlocked_exits():
    m = {"story": {"id": "m3", "characters": [{"id": "c9", "name": "Nia"}],
                   "acts": [{"index": 1, "title": "一"}],
                   "locations": [
                       {"id": "a", "name": "码头", "exits": ["集市"]},
                       {"id": "b", "name": "集市", "exits": ["码头", "钟楼"]},
                       {"id": "t", "name": "钟楼", "exits": ["集市"]}]},
         "secrets": []}
    st = {**runtime.default_state(), "location_id": "a"}
    dest = runtime.player_move(m, st, "去钟楼", "do")   # two hops away → still walks
    assert dest and dest["id"] == "t" and st["location_id"] == "t"


def test_player_move_never_fires_on_questions_orders_negations_or_locked():
    st = {**runtime.default_state(), "location_id": "hall"}
    assert runtime.player_move(MAP, st, "要不要一起去书房？", "say") is None
    assert runtime.player_move(MAP, st, "你去书房等我", "say") is None
    assert runtime.player_move(MAP, st, "让他去书房拿书", "say") is None
    assert runtime.player_move(MAP, st, "别去书房", "say") is None
    assert runtime.player_move(MAP, st, "去阁楼", "do") is None      # locked (needs f_loc)
    st["unlocked_fragment_ids"] = ["f_loc"]
    assert runtime.player_move(MAP, st, "去阁楼", "do") is None      # unlocked but no path in
    assert st["location_id"] == "hall"


def test_player_move_speaks_english_too():
    m = {"story": {"id": "m4", "characters": [], "acts": [{"index": 1, "title": "1"}],
                   "locations": [{"id": "x", "name": "Harbor", "exits": ["Old Lighthouse"]},
                                 {"id": "y", "name": "Old Lighthouse", "exits": ["Harbor"]}]},
         "secrets": []}
    st = {**runtime.default_state(), "location_id": "x"}
    dest = runtime.player_move(m, st, "I head back to the Old Lighthouse", "do")
    assert dest and dest["id"] == "y" and st["location_id"] == "y"


# ── 🔎 找人: "go find X" pops a confirm, and X is GUARANTEED to be there ──

def test_char_pin_overrides_schedule_until_you_leave():
    st = {**runtime.default_state(), "location_id": "hall", "act": 2}
    c = MAP["story"]["characters"][0]
    assert runtime.char_position(MAP, st, c) == "study"   # act-2 作息 says study
    st["char_pins"] = {"c1": "hall"}
    assert runtime.char_position(MAP, st, c) == "hall"    # …but the promised meeting wins
    assert any(x["id"] == "c1" for x in runtime.scene_characters(MAP, st))
    runtime.apply_move(MAP, st, "书房")                    # leaving the meeting place
    assert not st.get("char_pins")
    assert runtime.char_position(MAP, st, c) == "study"   # released back to her schedule


def test_seek_pops_a_confirm_and_pins_the_target():
    st = {**runtime.default_state(), "location_id": "study", "act": 1}
    out = runtime.run_turn(MAP, st, {"name": "我"}, "去找Mara", channel="say")
    mr = out.get("move_request")
    assert mr and mr.get("seek") and mr["to"] == "hall" and mr["by_name"] == "Mara"
    assert out["state"]["location_id"] == "study"          # not moved yet — awaiting confirm
    assert out["state"]["char_pins"] == {"c1": "hall"}     # she WILL be there
    assert any("Mara" in (b.get("text") or "") for b in out["beats"])


def test_seek_ignores_people_already_here_and_non_people():
    st = {**runtime.default_state(), "location_id": "hall", "act": 1}
    assert runtime.player_seek(MAP, st, "去找Mara", "say") is None     # she's right here
    st2 = {**runtime.default_state(), "location_id": "study", "act": 1}
    assert runtime.player_seek(MAP, st2, "找找有没有线索", "say") is None
    assert runtime.player_seek(MAP, st2, "别找Mara了", "say") is None


def test_apply_move_walks_multi_hop_now():
    m = {"story": {"id": "m5", "characters": [], "acts": [{"index": 1, "title": "一"}],
                   "locations": [
                       {"id": "a", "name": "码头", "exits": ["集市"]},
                       {"id": "b", "name": "集市", "exits": ["码头", "钟楼"]},
                       {"id": "t", "name": "钟楼", "exits": ["集市"]}]},
         "secrets": []}
    st = {**runtime.default_state(), "location_id": "a"}
    dest = runtime.apply_move(m, st, "钟楼")               # two hops → the walk is implied
    assert dest["id"] == "t" and st["location_id"] == "t"


# ── 场景不切换 fixes: new move verbs, single-exit leave, player-named emergent dest ──

SANDBOX_MAP = {
    "story": {
        "id": "sb", "sandbox": {"enabled": True},
        "characters": [{"id": "c1", "name": "Mara", "is_lead": True,
                        "home_location_id": "hall"}],
        "acts": [{"index": 1, "title": "一"}],
        "locations": [
            {"id": "hall", "name": "门厅", "detail": "一盏吊灯", "exits": ["书房"]},
            {"id": "study", "name": "书房", "detail": "书架", "exits": ["门厅"]},
        ],
    },
    "secrets": [],
}


def test_walk_into_verb_moves():
    st = {**runtime.default_state(), "location_id": "hall"}
    dest = runtime.player_move(MAP, st, "走进书房", channel="do")
    assert dest and dest["id"] == "study" and st["location_id"] == "study"


def test_directionless_leave_single_exit():
    # hall has exactly one exit (书房) → 「离开」 is unambiguous
    st = {**runtime.default_state(), "location_id": "hall"}
    dest = runtime.player_move(MAP, st, "离开", channel="do")
    assert dest and dest["id"] == "study"
    # 书房 also has one exit → straight back
    dest = runtime.player_move(MAP, st, "出去吧", channel="do")
    assert dest and dest["id"] == "hall"


def test_emergent_destination_offer_sandbox_only():
    st = {**runtime.default_state(), "location_id": "hall"}
    # sandbox + off-map name → offer it
    assert runtime.player_move_emergent(SANDBOX_MAP, st, "去后台", channel="do") == "后台"
    # known place → not emergent (player_move's business)
    assert runtime.player_move_emergent(SANDBOX_MAP, st, "去书房", channel="do") is None
    # deictics/questions/others-orders never generate a place
    assert runtime.player_move_emergent(SANDBOX_MAP, st, "去外面", channel="do") is None
    assert runtime.player_move_emergent(SANDBOX_MAP, st, "要不要去后台？", channel="do") is None
    assert runtime.player_move_emergent(SANDBOX_MAP, st, "你去后台", channel="do") is None
    # authored story → closed map, no generation
    assert runtime.player_move_emergent(MAP, st, "去后台", channel="do") is None
    # a character name is a seek, not a place
    assert runtime.player_move_emergent(SANDBOX_MAP, st, "去找Mara", channel="do") is None


def test_goal_recentered_on_embodied_character():
    st = {**runtime.default_state(), "act": 1}
    # generic player → the act's authored goal
    base = runtime.goal_for(SANDBOX_MAP, st)
    assert base == runtime.current_goal(SANDBOX_MAP, 1)
    # embodying a character WITH wants → THEIR agenda
    SANDBOX_MAP["story"]["characters"][0]["wants"] = "找到失踪的妹妹"
    st["player_character_id"] = "c1"
    assert runtime.goal_for(SANDBOX_MAP, st) == "找到失踪的妹妹"
    # a character without wants falls back to the act goal
    SANDBOX_MAP["story"]["characters"][0].pop("wants")
    assert runtime.goal_for(SANDBOX_MAP, st) == base


# ── 🧍 姿位账本: pose twin + roster anchor ───────────────────────────────────

def test_pose_twin_books_player_pose():
    st = {**runtime.default_state(), "location_id": "hall"}
    assert runtime.player_pose(st, "我坐在窗边", channel="do") == "坐在窗边"
    assert st["player_pos"] == {"text": "坐在窗边", "at": "hall"}
    # questions / negations / other people's bodies never book
    st2 = {**runtime.default_state(), "location_id": "hall"}
    assert runtime.player_pose(st2, "要不要坐下？", channel="do") is None
    assert runtime.player_pose(st2, "你坐下", channel="do") is None
    assert runtime.player_pose(st2, "别躺在这", channel="do") is None
    assert "player_pos" not in st2


def test_roster_carries_fresh_poses_only():
    st = {**runtime.default_state(), "location_id": "hall"}
    st["player_pos"] = {"text": "靠着吧台", "at": "hall"}
    st.setdefault("char_sim", {})["c1"] = {"pos": {"text": "坐在长椅上", "at": "hall"}}
    roster = runtime._physical_roster(MAP, st, {"name": "我"})
    first = roster.split("\n", 1)[0]
    assert "靠着吧台" in first and "坐在长椅上" in first and "姿位有连续性" in first
    # a pose booked in ANOTHER room is stale → ignored
    st["char_sim"]["c1"]["pos"]["at"] = "study"
    st["player_pos"]["at"] = "study"
    roster2 = runtime._physical_roster(MAP, st, {"name": "我"})
    assert "靠着吧台" not in roster2 and "坐在长椅上" not in roster2


# ── 🎬 关键帧: declared frames book, undeclared carry forward, POV guard ─────

def test_scene_frame_books_present_only():
    st = {**runtime.default_state(), "location_id": "hall"}
    directed = {"scene_frame": [
        {"name": "Mara", "frame": "退到门边握刀"},
        {"name": "不存在的人", "frame": "凭空出现"},
    ]}
    n = runtime.book_scene_frame(MAP, st, directed, sp_id=None)
    assert n == 1
    assert st["char_sim"]["c1"]["pos"] == {"text": "退到门边握刀", "at": "hall"}
    # the invalid name landed on the audit sheet as a rejection
    rejects = [a for a in st["last_audit"] if a["e"] == "frame.set" and not a["ok"]]
    assert len(rejects) == 1


def test_scene_frame_never_overrides_speaker_or_player():
    st = {**runtime.default_state(), "location_id": "hall",
          "player_character_id": "c1"}
    directed = {"scene_frame": [{"name": "Mara", "frame": "跪下求饶"}]}
    assert runtime.book_scene_frame(MAP, st, directed, sp_id=None) == 0


def test_pov_break_detection():
    bad = {"beats": [{"type": "description",
                      "text": "我咬住下唇，我数着尘埃，我控制不住地发抖。"}]}
    ok = {"beats": [{"type": "description",
                     "text": "你心里翻来覆去只有一个念头：我不能输，我不能先服软。"}]}
    dlg = {"beats": [{"type": "dialogue", "text": "我不去，我不想去，我就是不去。"}]}
    assert runtime._pov_break(bad) is True
    assert runtime._pov_break(ok) is False       # 你-anchored interiority is fine
    assert runtime._pov_break(dlg) is False      # dialogue speaks 我 freely


def test_unframed_names_lists_bodies_without_frames():
    st = {**runtime.default_state(), "location_id": "hall"}
    # Mara is present (home=hall) and has no frame yet → she needs 原画
    assert runtime.unframed_names(MAP, st) == ["Mara"]
    # a fresh frame removes her from the list
    st.setdefault("char_sim", {})["c1"] = {"pos": {"text": "坐在长椅上", "at": "hall"}}
    assert runtime.unframed_names(MAP, st) == []
    # a STALE frame (booked in another room) does not count
    st["char_sim"]["c1"]["pos"]["at"] = "study"
    assert runtime.unframed_names(MAP, st) == ["Mara"]


def test_arrival_pan_seeds_the_ledger():
    class ArriveLLM:
        def generate(self, prompt):
            assert prompt.get("arrive")
            return {"beats": [{"type": "description", "text": "门厅里灯影摇晃。"}],
                    "frames": [{"name": "Mara", "frame": "站在吊灯下擦拭烛台"}]}
    st = {**runtime.default_state(), "location_id": "hall"}
    txt = runtime.arrival_narration(MAP, st, {"name": "我"}, llm=ArriveLLM())
    assert "灯影" in txt
    assert st["char_sim"]["c1"]["pos"] == {"text": "站在吊灯下擦拭烛台", "at": "hall"}


def test_suggestions_always_three():
    # smart partial + weak template → padded to exactly 3, de-duped
    out = runtime.ensure_three_suggestions(["只有一条"], [], MAP)
    assert len(out) == 3 and out[0] == "只有一条"
    out2 = runtime.ensure_three_suggestions([], ["A", "A", "B"], MAP)
    assert len(out2) == 3 and out2[:2] == ["A", "B"]
    # already three smart → untouched order, still three
    out3 = runtime.ensure_three_suggestions(["一", "二", "三"], ["模板"], MAP)
    assert out3 == ["一", "二", "三"]


# ── 🎥 场记: extraction updates the ledger, validates names, flags conflicts ──

class TrackLLM:
    def __init__(self, out):
        self.out = out

    def generate(self, prompt):
        assert prompt.get("track_scene")
        return self.out


def test_tracker_books_frames_and_wear():
    st = {**runtime.default_state(), "location_id": "hall"}
    beats = [{"type": "description", "text": "Mara走到窗边，解下外套搭在臂弯。"}]
    llm = TrackLLM({"frames": [
        {"name": "Mara", "pos": "站在窗边", "doing": "望着街口", "wear": "解了外套"},
        {"name": "路人甲", "pos": "站着"},   # not on the roster → rejected
    ], "player": {"pos": "坐在长椅上"}, "contradictions": []})
    runtime.track_scene_frames(MAP, st, {"name": "我"}, beats, llm)
    e = st["char_sim"]["c1"]["pos"]
    assert e["text"] == "站在窗边·望着街口" and e["wear"] == "解了外套" and e["at"] == "hall"
    assert st["player_pos"]["text"] == "坐在长椅上"
    rejects = [a for a in st["last_audit"] if a["e"] == "track.update" and not a["ok"]]
    assert len(rejects) == 1
    # the roster line now carries the wear
    roster = runtime._physical_roster(MAP, st, {"name": "我"})
    assert "站在窗边·望着街口·着解了外套" in roster.split("\n", 1)[0]


def test_tracker_conflict_sets_note():
    st = {**runtime.default_state(), "location_id": "hall"}
    st.setdefault("char_sim", {})["c1"] = {"pos": {"text": "坐在长椅上", "at": "hall"}}
    beats = [{"type": "description", "text": "Mara忽然出现在门口。"}]
    llm = TrackLLM({"frames": [{"name": "Mara", "pos": "站在门口"}],
                    "contradictions": ["Mara上一帧坐在长椅上，正文无过渡地写她在门口"]})
    runtime.track_scene_frames(MAP, st, {"name": "我"}, beats, llm)
    assert st["char_sim"]["c1"]["pos"]["text"] == "站在门口"   # ledger follows the text
    assert "无过渡" in st["track_note"]


def test_tracker_fail_open():
    st = {**runtime.default_state(), "location_id": "hall"}
    st.setdefault("char_sim", {})["c1"] = {"pos": {"text": "坐在长椅上", "at": "hall"}}

    class BoomLLM:
        def generate(self, prompt):
            return {}   # aux degraded → previous frames stay untouched
    runtime.track_scene_frames(MAP, st, {"name": "我"},
                               [{"type": "description", "text": "风吹过门厅。"}], BoomLLM())
    assert st["char_sim"]["c1"]["pos"]["text"] == "坐在长椅上"


# ── 🎣 环境物件: 拿起X → 正文追认 → 入包 ─────────────────────────────────────

def test_pickup_ratified_by_prose():
    st = {**runtime.default_state(), "location_id": "hall"}
    # 拿起竹竿: nothing sources it (nobody carries one, never mentioned) → parked
    got = runtime.accept_item(MAP, st, "拿起竹竿", channel="do", history=[])
    assert got == [] and st["_pending_take"] == ["竹竿"]
    # this turn's prose ratifies the name → booked
    beats = [{"type": "description", "text": "他伸手抄起墙根那根青竹竿，掂了掂分量。"}]
    booked = runtime.settle_pending_takes(st, beats)
    assert booked == ["竹竿"]
    assert any(i["name"] == "竹竿" for i in st["inventory"])


def test_pickup_unratified_drops():
    st = {**runtime.default_state(), "location_id": "hall"}
    runtime.accept_item(MAP, st, "拿起屠龙宝刀", channel="do", history=[])
    booked = runtime.settle_pending_takes(
        st, [{"type": "description", "text": "墙角什么都没有，只有灰。"}])
    assert booked == [] and st["inventory"] == []
    rejects = [a for a in st["last_audit"] if a["e"] == "take" and not a["ok"]]
    assert len(rejects) == 1


def test_ba_stash_form_still_books_from_history():
    st = {**runtime.default_state(), "location_id": "hall"}
    hist = [{"role": "assistant", "content": "他把那根竹竿递到你面前。"}]
    got = runtime.accept_item(MAP, st, "把竹竿收进背包", channel="do", history=hist)
    assert got and got[0]["name"] == "竹竿"


def test_bad_place_names_never_mint_locations():
    st = {**runtime.default_state(), "location_id": "hall"}
    # 「回头看看…」 minted a location in prod — pronouns/gaze/question tails are barred
    for junk in ("回头看看他跟不跟", "去你那里", "去看看情况", "回味一下"):
        assert runtime.player_move_emergent(SANDBOX_MAP, st, junk, channel="do") is None, junk
    # legit new places still offer
    assert runtime.player_move_emergent(SANDBOX_MAP, st, "去炼金塔", channel="do") == "炼金塔"



def test_pov_break_catches_third_person_player():
    # embodying 萧薰儿: a description beat that NAMES her (3rd person, no 你) is a break
    third = {"beats": [{"type": "description", "text": "萧薰儿猛地甩开对方的手，贴到铁门前。"}]}
    assert runtime._pov_break(third, "萧薰儿") is True
    # correct second-person narration passes
    ok = {"beats": [{"type": "description", "text": "你猛地甩开萧炎的手，贴到铁门前。"}]}
    assert runtime._pov_break(ok, "萧薰儿") is False
    # a dialogue beat may name her freely
    dlg = {"beats": [{"type": "dialogue", "text": "萧薰儿说得对。"}]}
    assert runtime._pov_break(dlg, "萧薰儿") is False
    # no embodied name → falls back to 我-hijack only
    assert runtime._pov_break(third, "") is False
