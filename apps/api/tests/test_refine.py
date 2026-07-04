"""The four refinements: moods persist across scenes; authored cover stories speak
while the truth is locked (and shatter on confront); gifts become remembered
keepsakes; offscreen drama mints rumors that get passed on exactly once."""

from app.engine import gating, runtime

STORY = {
    "story": {"id": "s", "tuning": {"turns_per_slot": 1},
              "characters": [
                  {"id": "a", "name": "甲", "is_lead": True, "home_location_id": "hall"},
                  {"id": "b", "name": "乙", "home_location_id": "alley"},
                  {"id": "c", "name": "丙", "home_location_id": "alley"},
              ],
              "acts": [{"index": 1, "title": "一"}],
              "locations": [{"id": "hall", "name": "门厅", "detail": "x", "exits": ["后巷"]},
                            {"id": "alley", "name": "后巷", "detail": "y", "exits": ["门厅"]}]},
    "secrets": [
        {"id": "s1", "character_id": "a", "title": "那笔债",
         "fragments": [{"id": "f1", "content": "TRUTH_BODY", "retrieval_key": "债",
                        "cover": "COVER_LIE 他说那是给乡下老母亲的汇款。",
                        "unlock": {"affinity_min": 999}}]},
    ],
}


class RefineLLM:
    def __init__(self, **fields):
        self.fields = fields
        self.prompts = []

    def generate(self, prompt):
        for k in ("offscreen", "arrive", "farewell", "compose_msg", "opening_hook"):
            if prompt.get(k):
                self.prompts.append(prompt)
                return self.fields.get(k + "_out", {})
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


def test_mood_persists_and_a_day_heals_it():
    st = runtime.default_state()
    st["location_id"] = "hall"
    st = runtime.run_turn(STORY, st, {"name": "我"}, "你太让我失望了", channel="say",
                          llm=RefineLLM(self_state="被伤到了", next_speakers=[]))["state"]
    assert st["char_sim"]["a"]["mood"]["text"] == "被伤到了"
    llm2 = RefineLLM(next_speakers=[])
    runtime.run_turn(STORY, st, {"name": "我"}, "还好吗", channel="say", llm=llm2)
    cond = next(p["condition"] for p in llm2.prompts if p.get("speaker_name") == "甲")
    assert cond["mood"] == "被伤到了"                      # the next scene opens on it
    st["clock"] = {"day": 3, "slot": 0, "turns_in_slot": 0}
    assert runtime._carried_mood(st, "a") == ""            # a day later, the edge dulls


def test_cover_story_speaks_until_the_truth_replaces_it():
    st = runtime.default_state()
    frags = gating.iter_fragments(STORY)
    ctx = gating.build_context("a", frags, st)
    assert ctx["covers"] == [{"secret_title": "那笔债",
                              "content": "COVER_LIE 他说那是给乡下老母亲的汇款。"}]
    assert "TRUTH_BODY" not in str(ctx)                    # the lie never smuggles truth
    # the live prompt carries the unified 口径…
    llm = RefineLLM(next_speakers=[])
    st["location_id"] = "hall"
    runtime.run_turn(STORY, st, {"name": "我"}, "那笔债是怎么回事", channel="say", llm=llm)
    assert any("COVER_LIE" in str((p.get("context") or {}).get("covers"))
               for p in llm.prompts)
    # …and once the truth is unlocked, the cover falls silent
    st2 = runtime.default_state()
    st2["unlocked_fragment_ids"] = ["f1"]
    assert gating.build_context("a", frags, st2)["covers"] == []


def test_confront_shatters_the_authored_lie(monkeypatch):
    monkeypatch.setattr(runtime, "_roll_check",
                        lambda risk: {"risk": risk, "roll": 1, "outcome": "success"})
    content = {"story": {**STORY["story"]}, "secrets": [
        {"id": "s1", "character_id": "a", "title": "那笔债",
         "fragments": [{"id": "f0", "content": "KNOWN", "retrieval_key": "债",
                        "unlock": {"asks_min": 0}},
                       {"id": "f1", "content": "TRUTH_BODY", "retrieval_key": "深",
                        "cover": "COVER_LIE 汇款说辞。",
                        "unlock": {"affinity_min": 999}}]}]}
    st = runtime.default_state()
    st["location_id"] = "hall"
    st["unlocked_fragment_ids"] = ["f0"]
    llm = RefineLLM()
    for kind, payload in runtime.confront_stream(content, st, {"name": "我"}, "f0", "a", llm=llm):
        pass
    conf = next(p["confrontation"] for p in llm.prompts if p.get("confrontation"))
    assert "COVER_LIE" in conf["shattered"]                # the lie collapses on stage


def test_gift_becomes_a_remembered_keepsake():
    st = runtime.default_state()
    st["location_id"] = "hall"
    st["inventory"] = [{"name": "银簪", "detail": "旧物"}]
    out = runtime.run_turn(STORY, st, {"name": "我"}, "这个送给你", channel="say",
                           llm=RefineLLM(gift="银簪|收|喜", next_speakers=[]))
    st = out["state"]
    assert st["inventory"] == []                            # it left the pocket…
    assert st["char_sim"]["a"]["keepsakes"][0]["name"] == "银簪"
    assert st["rel"]["a"]["closeness"] > 5
    assert any(m["kind"] == "gift" and m["liked"] for m in out["moments"])
    assert runtime.character_profile(STORY, st, "a")["keepsakes"] == ["银簪"]
    # …and their next scene knows they carry it
    llm2 = RefineLLM(next_speakers=[])
    runtime.run_turn(STORY, st, {"name": "我"}, "在想什么", channel="say", llm=llm2)
    cond = next(p["condition"] for p in llm2.prompts if p.get("speaker_name") == "甲")
    assert cond["keepsakes"] == ["银簪"]
    # a refused gift stays with the player
    st3 = runtime.default_state()
    st3["location_id"] = "hall"
    st3["inventory"] = [{"name": "金锭"}]
    out3 = runtime.run_turn(STORY, st3, {"name": "我"}, "收下吧", channel="say",
                            llm=RefineLLM(gift="金锭|拒", next_speakers=[]))
    assert out3["state"]["inventory"][0]["name"] == "金锭"


def test_offscreen_drama_mints_a_rumor_told_once():
    st = runtime.default_state()
    st["location_id"] = "hall"                              # 乙丙 are off in the alley
    llm = RefineLLM(offscreen_out={"delta": -1, "rumor": "听说乙和丙昨夜在后巷吵红了脸"},
                    next_speakers=[])
    st = runtime.run_turn(STORY, st, {"name": "我"}, "聊聊", channel="say", llm=llm)["state"]
    assert st["rumors"] and st["rumors"][0]["heard"] is False
    assert runtime.npc_stance(st, "b", "c") == {"stance": -1, "label": "不睦"}
    # the next primary passes it on — exactly once
    llm2 = RefineLLM(next_speakers=[])
    st = runtime.run_turn(STORY, st, {"name": "我"}, "最近有什么新鲜事", channel="say",
                          llm=llm2)["state"]
    assert any("吵红了脸" in (p.get("rumor") or "") for p in llm2.prompts)
    assert st["rumors"][0]["heard"] is True
    llm3 = RefineLLM(next_speakers=[])
    runtime.run_turn(STORY, st, {"name": "我"}, "还有呢", channel="say", llm=llm3)
    assert all(not (p.get("rumor") or "") for p in llm3.prompts)
