"""The dynamic world: ☠️ character death (gone for good, remembered), 👋 emergent
mid-story characters (quota-capped), 🎖 evolving player identity, 🎒 inventory
(pocket / stash / retrieve / takeable props / authored starting items)."""

from app.engine import runtime

STORY = {
    "story": {"id": "s", "characters": [
        {"id": "a", "name": "甲", "is_lead": True},
        {"id": "b", "name": "乙"},
    ], "acts": [{"index": 1, "title": "一"}],
       "locations": [{"id": "hall", "name": "门厅", "detail": "一盏吊灯", "exits": [],
                      "props": [{"id": "p1", "name": "带血的钥匙", "take": True,
                                 "detail": "冰凉，齿口有暗红的痕。"}]}]},
    "secrets": [],
}


class WorldLLM:
    """Primary emits configurable dynamic-world judgments."""

    def __init__(self, **fields):
        self.fields = fields
        self.prompts = []

    def generate(self, prompt):
        if prompt.get("intro") or prompt.get("observe") or prompt.get("suggest") or prompt.get("risk_judge"):
            return {"risk": 100} if prompt.get("risk_judge") else \
                   {"beats": [{"type": "description", "speaker_name": None, "text": "x"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}
        self.prompts.append(prompt)
        out = {"beats": [{"type": "dialogue", "speaker_name": prompt.get("speaker_name"), "text": "嗯"}],
               "affinity_delta": 0, "advance_act": False, "ending": None}
        if prompt.get("group_mode") in ("primary", None):
            out.update(self.fields)
        return out


def test_death_removes_from_scene_and_is_remembered():
    st = runtime.default_state()
    # deaths are TWO-STAGE now (char_sim): the first blow books 濒死, the second is final
    runtime.set_char_hp(st, "b", "dying")
    out = runtime.run_turn(STORY, st, {"name": "我"}, "动手吧", channel="say",
                           llm=WorldLLM(died="乙", next_speakers=[]))
    st = out["state"]
    assert "b" in st["dead_character_ids"]
    assert any(m["kind"] == "death" and m["name"] == "乙" for m in out["moments"])
    # gone from the scene, the cast, and the map
    assert all(c["id"] != "b" for c in runtime.scene_characters(STORY, st))
    assert all(c["id"] != "b" for c in runtime.cast_for(STORY, 1, state=st))
    # …but remembered: the next turn's prompts carry the death
    llm2 = WorldLLM()
    runtime.run_turn(STORY, st, {"name": "我"}, "唉", channel="say", llm=llm2)
    assert "乙" in (llm2.prompts[0].get("deaths") or [])
    assert runtime.journal(STORY, st)["deaths"] == ["乙"]


def test_emergent_character_joins_and_quota_holds():
    st = runtime.default_state()
    content = {"story": {**STORY["story"], "characters": [dict(c) for c in STORY["story"]["characters"]]},
               "secrets": []}
    out = runtime.run_turn(content, st, {"name": "我"}, "有人来了？", channel="say",
                           llm=WorldLLM(new_char="老周｜巡逻队的老班长，鬓角花白", next_speakers=[]))
    assert out["content_mutated"] is True
    names = [c.get("name") for c in content["story"]["characters"]]
    assert "老周" in names
    nc = next(c for c in content["story"]["characters"] if c.get("name") == "老周")
    assert nc.get("generated") and nc.get("home_location_id") == "hall"
    assert any(m["kind"] == "arrival" for m in out["moments"])
    # duplicate name is refused; quota (tuning) caps the cast growth
    out2 = runtime.run_turn(content, out["state"], {"name": "我"}, "又来？", channel="say",
                            llm=WorldLLM(new_char="老周｜重复", next_speakers=[]))
    assert names.count("老周") == 1 and out2["content_mutated"] is False


def test_identity_change_tracked_and_injected():
    st = runtime.default_state()
    out = runtime.run_turn(STORY, st, {"name": "我"}, "宣读任命吧", channel="say",
                           llm=WorldLLM(identity="巡警队警长", next_speakers=[]))
    st = out["state"]
    assert st["identity"] == "巡警队警长"
    assert st["identity_log"][-1]["text"] == "巡警队警长"
    assert any(m["kind"] == "identity" for m in out["moments"])
    # next turn: NPCs see the evolved identity in the player's persona background
    llm2 = WorldLLM()
    runtime.run_turn(STORY, st, {"name": "我"}, "早", channel="say", llm=llm2)
    assert "巡警队警长" in (llm2.prompts[0].get("persona") or {}).get("background", "")


def test_inventory_gain_lose_stash_retrieve():
    st = runtime.default_state()
    out = runtime.run_turn(STORY, st, {"name": "我"}, "收下吧", channel="say",
                           llm=WorldLLM(gained="铜哨", next_speakers=[]))
    st = out["state"]
    assert [i["name"] for i in st["inventory"]] == ["铜哨"]
    # stash it here, then walk-and-retrieve deterministically
    out2 = runtime.run_turn(STORY, st, {"name": "我"}, "先放这儿", channel="say",
                            llm=WorldLLM(stashed="铜哨", next_speakers=[]))
    st = out2["state"]
    assert st["inventory"] == [] and st["stashes"]["hall"][0]["name"] == "铜哨"
    out3 = runtime.run_turn(STORY, st, {"name": "我"}, "我把铜哨取回来", channel="do",
                            llm=WorldLLM(next_speakers=[]))
    st = out3["state"]
    assert [i["name"] for i in st["inventory"]] == ["铜哨"] and not st["stashes"]
    # losing something you don't have is ignored
    out4 = runtime.run_turn(STORY, st, {"name": "我"}, "交出去", channel="say",
                            llm=WorldLLM(lost="不存在的东西", next_speakers=[]))
    assert [i["name"] for i in out4["state"]["inventory"]] == ["铜哨"]


def test_takeable_prop_goes_to_pocket():
    st = {**runtime.default_state(), "location_id": "hall"}
    out = runtime.run_turn(STORY, st, {"name": "我"}, "我捡起那把带血的钥匙", channel="do",
                           llm=WorldLLM(next_speakers=[]))
    assert any(i["name"] == "带血的钥匙" for i in out["state"]["inventory"])
