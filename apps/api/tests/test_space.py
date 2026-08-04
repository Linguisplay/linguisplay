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


def test_director_move_is_a_confirmable_request_not_a_teleport(map_writes_on):
    """The MODEL can only PROPOSE a move (move_invite) — the player stays put until they
    confirm (apply_move, the /move endpoint). An off-map destination becomes an emergent
    generate-on-accept offer, never a silent teleport. (The player's OWN first-person
    「去X」 now walks immediately via player_move — that path is covered in
    test_place_gameplay; here the input asks the CHARACTER to lead, so it stays a
    confirmable invite.)"""
    class MoverLLM:
        def __init__(self, dest):
            self.dest = dest

        def generate(self, prompt):
            if prompt.get("describe_place"):   # 🧑‍⚖️ 判官孪生: 铸造要有干净地名
                nm = (prompt.get("place_name") or "").strip()
                return {"name": nm[:12], "detail": f"{nm}的样子。"}
            if prompt.get("intro") or prompt.get("observe") or prompt.get("suggest"):
                return {"beats": [{"type": "description", "speaker_name": None, "text": "x"}],
                        "affinity_delta": 0, "advance_act": False, "ending": None}
            return {"beats": [{"type": "dialogue", "speaker_name": prompt.get("speaker_name"), "text": "嗯"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None, "move_invite": self.dest}

    # a known, connected destination → a confirm request; NOT moved yet
    st = runtime.default_state()
    out = runtime.run_turn(MAP, st, {"name": "我"}, "带我去书房吧", channel="do", llm=MoverLLM("书房"))
    assert out["state"]["location_id"] in (None, "hall")   # unmoved until the player confirms
    assert out["move_request"] and out["move_request"]["to"] == "study"
    # confirming actually moves
    dest = runtime.apply_move(MAP, out["state"], "书房")
    assert dest["id"] == "study" and out["state"]["location_id"] == "study"

    # an off-map destination → 提及即立档 (Yi 2026-07-20): the place is MINTED into the
    # world at mention time; the chip is a normal confirmable move, still no teleport
    st2 = {**runtime.default_state(), "location_id": "hall"}
    out2 = runtime.run_turn(MAP, st2, {"name": "我"}, "去天台", channel="do", llm=MoverLLM("天台"))
    assert out2["state"]["location_id"] == "hall"
    assert out2["move_request"] and out2["move_request"].get("minted") is True
    assert out2["move_request"].get("to")            # 已立档: chip 指向真实 id
    assert out2["move_request"]["to_name"] == "天台"


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


def test_generic_place_never_mints(map_writes_on):
    """🧑‍⚖️ 铸造判官 (Yi 2026-07-22 实弹: 「换个地方聊」被铸成地点「个地方」上了地图):
    泛指碎片预筛驳回; LLM 提炼不出干净地名也驳回 — 宁可没有确认条, 不许垃圾上地图。
    涌现人物安家 (invent) 例外: 泛指交给模型发明贴切去处。"""
    import copy

    class JunkLLM:
        def generate(self, prompt):
            if prompt.get("describe_place"):
                # 模型把泛指原样回吐 (实弹路径) — 判官必须拦住
                return {"name": prompt.get("place_name", ""), "detail": "x"}
            return {"beats": [{"type": "dialogue", "speaker_name": "甲", "text": "好啊"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None,
                    "move_invite": "个地方"}

    content = copy.deepcopy(MAP)
    st = {**runtime.default_state(), "location_id": "hall"}
    n0 = len(content["story"]["locations"])
    out = runtime.run_turn(content, st, {"name": "我"}, "我们换个地方聊", channel="say",
                           llm=JunkLLM())
    assert out.get("move_request") is None                    # 没有垃圾确认条
    assert len(content["story"]["locations"]) == n0           # 地图没长垃圾
    # 直接调用: 泛指预筛在 LLM 之前就驳回
    assert runtime.generate_and_move(content, st, "个地方", llm=JunkLLM(), move=False) is None
    assert runtime.generate_and_move(content, st, "别处", llm=JunkLLM(), move=False) is None
    # 模型答「无」(MockLLM 判官孪生) → 驳回; invent 模式泛指改为发明去处
    from app.engine.llm import MockLLM
    assert runtime.generate_and_move(content, st, "安静点的地方", llm=MockLLM(),
                                     move=False) is None
    inv = runtime.generate_and_move(content, st, "个地方", llm=MockLLM(),
                                    move=False, invent=True)
    assert inv and inv["name"] == "路边的凉棚" and inv.get("generated")
