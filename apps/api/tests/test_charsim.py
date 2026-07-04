"""The character simulation sheet: DETERMINISTIC positions (nobody is 'everywhere' in a
story with a map; model moves are validated and booked), graded life state (two-stage
deaths — only the dying can die; wounds move one step and can heal), and persisted
intents that feed the character's next scene."""

from app.engine import runtime

STORY = {
    "story": {"id": "s", "tuning": {"turns_per_slot": 0},
              "characters": [
                  {"id": "a", "name": "甲", "is_lead": True},          # no home: pins to opening
                  {"id": "b", "name": "乙"},                           # no home: pins to opening
                  {"id": "c", "name": "丙", "home_location_id": "alley"},
              ],
              "acts": [{"index": 1, "title": "一"}],
              "locations": [{"id": "hall", "name": "门厅", "detail": "一盏吊灯", "exits": ["后巷"]},
                            {"id": "alley", "name": "后巷", "detail": "潮湿", "exits": ["门厅"]}]},
    "secrets": [],
}


class SimLLM:
    def __init__(self, **fields):
        self.fields = fields
        self.prompts = []

    def generate(self, prompt):
        if prompt.get("intro") or prompt.get("observe") or prompt.get("suggest") \
                or prompt.get("risk_judge") or prompt.get("arrive") or prompt.get("farewell"):
            if prompt.get("risk_judge"):
                return {"risk": 100}
            if prompt.get("arrive") or prompt.get("farewell"):
                return {}
            return {"beats": [{"type": "description", "speaker_name": None, "text": "x"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}
        self.prompts.append(prompt)
        out = {"beats": [{"type": "dialogue", "speaker_name": prompt.get("speaker_name"), "text": "嗯"}],
               "affinity_delta": 0, "advance_act": False, "ending": None}
        if prompt.get("group_mode") in ("primary", None):
            out.update(self.fields)
        return out


def test_nobody_is_everywhere_anymore():
    st = runtime.default_state()
    st["location_id"] = "hall"
    here = {c["id"] for c in runtime.scene_characters(STORY, st)}
    assert here == {"a", "b"}                    # homeless chars pin to the opening place
    st["location_id"] = "alley"
    here2 = {c["id"] for c in runtime.scene_characters(STORY, st)}
    assert here2 == {"c"}                        # …and do NOT follow you around
    # mapless stories keep the legacy everyone-everywhere behavior
    mapless = {"story": {"id": "m", "characters": [{"id": "a", "name": "甲"}],
                         "acts": [{"index": 1, "title": "一"}]}, "secrets": []}
    assert runtime.scene_characters(mapless, runtime.default_state())


def test_model_moves_are_validated_and_booked():
    st = runtime.default_state()
    st["location_id"] = "hall"
    out = runtime.run_turn(STORY, st, {"name": "我"}, "你先去后巷等我", channel="say",
                           llm=SimLLM(next_speakers=[],
                                      npc_moves=[{"who": "乙", "to": "后巷"},
                                                 {"who": "丙", "to": "门厅"},      # 丙 not in scene
                                                 {"who": "甲", "to": "月球"}]))    # no such place
    st = out["state"]
    assert st["char_sim"]["b"]["pos"] == "alley"
    assert runtime.char_position(STORY, st, {"id": "b", "name": "乙"}) == "alley"
    assert "c" not in (st.get("char_sim") or {}) or not st["char_sim"].get("c", {}).get("pos")
    assert not (st.get("char_sim") or {}).get("a", {}).get("pos")
    # the departure was narrated by the roster diff, with the destination
    texts = [b.get("text", "") for b in out["beats"]]
    assert any("乙" in t and ("后巷" in t or "走" in t) for t in texts)
    # and the map now shows him THERE
    mp = runtime.map_view(STORY, st)
    alley = next(n for n in mp["nodes"] if n["id"] == "alley")
    assert "乙" in alley["chars"]


def test_two_stage_death_and_healing():
    st = runtime.default_state()
    st["location_id"] = "hall"
    # a killing blow on a healthy body books 濒死, not death
    out = runtime.run_turn(STORY, st, {"name": "我"}, "动手", channel="say",
                           llm=SimLLM(died="乙", next_speakers=[]))
    st = out["state"]
    assert "b" not in st["dead_character_ids"]
    assert runtime.char_hp(st, "b") == "dying"
    assert any(m["kind"] == "dying" for m in out["moments"])
    assert any("还来得及" in (b.get("text") or "") for b in out["beats"])
    # the roster marks the wounded for every prompt; healing steps back down
    llm2 = SimLLM(harmed="乙|好转", next_speakers=[])
    st = runtime.run_turn(STORY, st, {"name": "我"}, "撑住", channel="say", llm=llm2)["state"]
    assert runtime.char_hp(st, "b") == "hurt"
    assert any("重伤濒死" in (p.get("roster") or "") for p in llm2.prompts)
    # …but a second blow on the dying is final
    st2 = runtime.default_state()
    st2["location_id"] = "hall"
    runtime.set_char_hp(st2, "b", "dying")
    out3 = runtime.run_turn(STORY, st2, {"name": "我"}, "补上一刀", channel="say",
                            llm=SimLLM(died="乙", next_speakers=[]))
    assert "b" in out3["state"]["dead_character_ids"]
    assert runtime.char_hp(out3["state"], "b") == "dead"


def test_intent_persists_into_the_next_scene():
    st = runtime.default_state()
    st["location_id"] = "hall"
    st = runtime.run_turn(STORY, st, {"name": "我"}, "接下来怎么办", channel="say",
                          llm=SimLLM(self_intent="今夜去查配电间", next_speakers=[]))["state"]
    assert st["char_sim"]["a"]["intent"] == "今夜去查配电间"
    llm2 = SimLLM(next_speakers=[])
    runtime.run_turn(STORY, st, {"name": "我"}, "想好了吗", channel="say", llm=llm2)
    cond = next(p.get("condition") for p in llm2.prompts if p.get("speaker_name") == "甲")
    assert cond["intent"] == "今夜去查配电间"
