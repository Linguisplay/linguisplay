"""Scene interaction verbs: crafting consumes real materials; snatching needs the fate
roll on your side and the victim remembers; trading swaps both ends for real. NPC
possessions are lazily seeded from their authored items and visible on the dossier."""

from app.engine import runtime

STORY = {
    "story": {"id": "s", "tuning": {"turns_per_slot": 0},
              "characters": [
                  {"id": "a", "name": "甲", "is_lead": True,
                   "items": [{"name": "黄铜怀表", "detail": "老物件"},
                             {"name": "钥匙串"}]},
              ],
              "acts": [{"index": 1, "title": "一"}],
              "locations": [{"id": "hall", "name": "门厅", "detail": "x", "exits": []}],
              "pressure": {"name": "风声", "ending_id": None, "levels": []}},
    "secrets": [],
}


class ActLLM:
    def __init__(self, **fields):
        self.fields = fields
        self.risk = fields.pop("risk", 100)

    def generate(self, prompt):
        if prompt.get("risk_judge"):
            return {"risk": self.risk}
        if prompt.get("intro") or prompt.get("observe") or prompt.get("suggest") \
                or prompt.get("arrive") or prompt.get("farewell") or prompt.get("offscreen"):
            return {} if (prompt.get("arrive") or prompt.get("farewell")
                          or prompt.get("offscreen")) else \
                   {"beats": [{"type": "description", "speaker_name": None, "text": "x"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}
        out = {"beats": [{"type": "dialogue", "speaker_name": prompt.get("speaker_name"), "text": "嗯"}],
               "affinity_delta": 0, "advance_act": False, "ending": None}
        if prompt.get("group_mode") in ("primary", None):
            out.update(self.fields)
        return out


def _st(inv=None):
    st = runtime.default_state()
    st["location_id"] = "hall"
    if inv:
        st["inventory"] = [{"name": n} for n in inv]
    return st


def test_crafting_consumes_materials_or_refuses():
    out = runtime.run_turn(STORY, _st(["麻绳", "竹竿"]), {"name": "我"}, "把它们绑成一根撬棍",
                           channel="say", llm=ActLLM(crafted="简易撬棍|麻绳、竹竿", next_speakers=[]))
    names = [i["name"] for i in out["state"]["inventory"]]
    assert names == ["简易撬棍"]
    assert any(m.get("verb") == "crafted" for m in out["moments"])
    # a missing material voids the whole attempt — nothing is consumed
    out2 = runtime.run_turn(STORY, _st(["麻绳"]), {"name": "我"}, "做撬棍",
                            channel="say", llm=ActLLM(crafted="简易撬棍|麻绳、竹竿", next_speakers=[]))
    assert [i["name"] for i in out2["state"]["inventory"]] == ["麻绳"]


def test_crafting_respects_a_failed_roll(monkeypatch):
    monkeypatch.setattr(runtime, "_roll_check",
                        lambda risk: {"risk": risk, "roll": 99, "outcome": "fail"})
    out = runtime.run_turn(STORY, _st(["麻绳", "竹竿"]), {"name": "我"}, "绑一根撬棍",
                           channel="do", llm=ActLLM(risk=50, crafted="简易撬棍|麻绳、竹竿",
                                                    next_speakers=[]))
    assert {i["name"] for i in out["state"]["inventory"]} == {"麻绳", "竹竿"}


def test_snatch_transfers_and_the_victim_remembers(monkeypatch):
    monkeypatch.setattr(runtime, "_roll_check",
                        lambda risk: {"risk": risk, "roll": 1, "outcome": "success"})
    out = runtime.run_turn(STORY, _st(), {"name": "我"}, "一把夺过他的怀表",
                           channel="do", llm=ActLLM(risk=40, taken="黄铜怀表|甲",
                                                    next_speakers=[]))
    st = out["state"]
    assert any(i["name"] == "黄铜怀表" for i in st["inventory"])
    assert all(i["name"] != "黄铜怀表" for i in runtime.char_items(STORY, st, "a"))
    assert st["rel"]["a"]["closeness"] < 5                      # it cost the relationship
    assert st["pressure"] == 8                                  # and made noise
    assert any("抢走" in e["text"] for e in st["rel_log"]["a"])
    # a failed roll = no transfer, whatever the model claims
    monkeypatch.setattr(runtime, "_roll_check",
                        lambda risk: {"risk": risk, "roll": 99, "outcome": "fail"})
    out2 = runtime.run_turn(STORY, _st(), {"name": "我"}, "再抢一次",
                            channel="do", llm=ActLLM(risk=40, taken="钥匙串|甲",
                                                     next_speakers=[]))
    assert all(i["name"] != "钥匙串" for i in out2["state"]["inventory"])


def test_trade_swaps_both_ends_for_real():
    out = runtime.run_turn(STORY, _st(["银簪"]), {"name": "我"}, "用银簪换你的怀表如何",
                           channel="say", llm=ActLLM(trade="银簪|黄铜怀表", next_speakers=[]))
    st = out["state"]
    assert [i["name"] for i in st["inventory"]] == ["黄铜怀表"]
    their = [i["name"] for i in runtime.char_items(STORY, st, "a")]
    assert "银簪" in their and "黄铜怀表" not in their
    assert st["rel"]["a"]["closeness"] > 5                      # a fair deal builds rapport
    # trading something you don't have refuses cleanly
    out2 = runtime.run_turn(STORY, _st(), {"name": "我"}, "拿金子换",
                            channel="say", llm=ActLLM(trade="金锭|钥匙串", next_speakers=[]))
    assert out2["state"]["inventory"] == []


def test_stash_is_deterministic_and_retrieve_hears_speech():
    # 「把X放在这里」books the stash by ENGINE, no model judgment needed
    out = runtime.run_turn(STORY, _st(["黄铜怀表", "麻绳"]), {"name": "我"},
                           "我把黄铜怀表放在这里，藏好", channel="do",
                           llm=ActLLM(next_speakers=[]))
    st = out["state"]
    assert [i["name"] for i in st["inventory"]] == ["麻绳"]
    assert st["stashes"]["hall"][0]["name"] == "黄铜怀表"
    assert any(m.get("verb") == "stashed" for m in out["moments"])
    assert any("收放在了这里" in b.get("text", "") for b in out["beats"])
    # …and 说「取回」 works too (the backpack tip says to just say it)
    out2 = runtime.run_turn(STORY, st, {"name": "我"}, "取回黄铜怀表", channel="say",
                            llm=ActLLM(next_speakers=[]))
    st2 = out2["state"]
    assert any(i["name"] == "黄铜怀表" for i in st2["inventory"]) and not st2["stashes"]
    # handing over is NOT stashing: the gift phrasing stays with the judgment path
    out3 = runtime.run_turn(STORY, _st(["银簪"]), {"name": "我"},
                            "我把银簪放在你手里，送给你", channel="say",
                            llm=ActLLM(next_speakers=[]))
    assert [i["name"] for i in out3["state"]["inventory"]] == ["银簪"]
    assert not out3["state"].get("stashes")


def test_world_facts_persist_dedupe_and_ground_the_place():
    # a judged lasting change is booked to THIS place and served back to every scene
    out = runtime.run_turn(STORY, _st(), {"name": "我"}, "一脚踹向大门", channel="say",
                           llm=ActLLM(world_fact="正门被撞开了一道缝", next_speakers=[]))
    st = out["state"]
    assert st["place_facts"]["hall"][0]["text"] == "正门被撞开了一道缝"
    assert any(m["kind"] == "world" for m in out["moments"])
    assert "正门被撞开了一道缝" in runtime._physical_place(STORY, st)
    # the same fact never books twice
    st = runtime.run_turn(STORY, st, {"name": "我"}, "再看看门", channel="say",
                          llm=ActLLM(world_fact="正门被撞开了一道缝。", next_speakers=[]))["state"]
    assert len(st["place_facts"]["hall"]) == 1


def test_homeless_conjured_cast_gets_anchored():
    content = {"story": {"id": "s", "characters": [
        {"id": "g1", "name": "甲", "generated": True},
        {"id": "g2", "name": "乙", "generated": True, "home_location_id": "elsewhere"},
        {"id": "a1", "name": "丙"},                       # authored ubiquitous stays so
    ], "locations": [{"id": "L", "name": "码头", "detail": "x", "exits": []}]},
        "secrets": []}
    runtime.anchor_homeless_cast(content, "L")
    chars = {c["id"]: c for c in content["story"]["characters"]}
    assert chars["g1"]["home_location_id"] == "L"
    assert chars["g2"]["home_location_id"] == "elsewhere"   # an existing home is kept
    assert "home_location_id" not in chars["a1"]            # authored chars untouched


def test_possessions_visible_on_the_dossier():
    st = _st()
    prof = runtime.character_profile(STORY, st, "a")
    assert prof["carrying"] == ["黄铜怀表", "钥匙串"]
