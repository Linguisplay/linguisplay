"""🃏 证据对峙: an unlocked clue becomes a verb — slam it down in front of its owner.
Success pries the secret's next layer open on the spot (evidence beats gates) at a
relationship cost; failure hardens them; a 大失败 feeds the pressure meter. The whole
thing validates eagerly and streams the /play contract."""

import pytest

from app.engine import runtime

STORY = {
    "story": {"id": "s",
              "characters": [{"id": "a", "name": "甲", "is_lead": True},
                             {"id": "b", "name": "乙"}],
              "acts": [{"index": 1, "title": "一",
                        "advance": {"required_fragment_ids": ["f2"]}},
                       {"index": 2, "title": "二"}],
              "locations": [{"id": "hall", "name": "门厅", "detail": "一盏吊灯", "exits": []}],
              "pressure": {"name": "风声", "ending_id": None, "levels": []}},
    "secrets": [
        {"id": "s1", "character_id": "a", "title": "那笔债",
         "fragments": [{"id": "f1", "content": "EV_KNOWN 他每月给人送钱。", "retrieval_key": "送钱",
                        "unlock": {"asks_min": 0}},
                       {"id": "f2", "content": "EV_LOCKED 那是他兄弟的抚恤。", "retrieval_key": "抚恤",
                        "unlock": {"affinity_min": 999}}]},
        {"id": "s2", "character_id": "b", "title": "别的事",
         "fragments": [{"id": "g1", "content": "OTHER", "retrieval_key": "x",
                        "unlock": {"affinity_min": 999}}]},
    ],
}


class ConfrontLLM:
    def __init__(self):
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return {"beats": [{"type": "dialogue", "speaker_name": prompt.get("speaker_name"),
                           "text": "……你都知道了。"}],
                "affinity_delta": 0, "advance_act": False, "ending": None}


def _ready_state():
    st = runtime.default_state()
    st["unlocked_fragment_ids"] = ["f1"]
    return st


def _drain(gen):
    out = {"beats": [], "dice": None, "final": None}
    for kind, payload in gen:
        if kind == "dice":
            out["dice"] = payload
        elif kind == "beat":
            out["beats"].append(payload)
        else:
            out["final"] = payload
    return out


def test_validation_is_eager_and_readable():
    st = _ready_state()
    with pytest.raises(ValueError, match="没有这条线索"):
        runtime.confront_stream(STORY, st, {"name": "我"}, "nope", "a", llm=ConfrontLLM())
    with pytest.raises(ValueError, match="还没真正掌握"):
        runtime.confront_stream(STORY, st, {"name": "我"}, "f2", "a", llm=ConfrontLLM())
    with pytest.raises(ValueError, match="当事人"):
        runtime.confront_stream(STORY, st, {"name": "我"}, "f1", "b", llm=ConfrontLLM())
    st2 = _ready_state()
    st2["dead_character_ids"] = ["a"]
    with pytest.raises(ValueError, match="不在人世"):
        runtime.confront_stream(STORY, st2, {"name": "我"}, "f1", "a", llm=ConfrontLLM())
    st3 = _ready_state()
    st3["mode"] = "god"
    with pytest.raises(ValueError, match="旁观者"):
        runtime.confront_stream(STORY, st3, {"name": "我"}, "f1", "a", llm=ConfrontLLM())
    st4 = _ready_state()
    st4["unlocked_fragment_ids"] = ["f1", "f2"]
    with pytest.raises(ValueError, match="没什么可瞒"):
        runtime.confront_stream(STORY, st4, {"name": "我"}, "f1", "a", llm=ConfrontLLM())


def test_success_forces_the_next_layer_open(monkeypatch):
    monkeypatch.setattr(runtime, "_roll_check",
                        lambda risk: {"risk": risk, "roll": 1, "outcome": "success"})
    llm = ConfrontLLM()
    st = _ready_state()
    out = _drain(runtime.confront_stream(STORY, st, {"name": "我"}, "f1", "a", llm=llm))
    fin = out["final"]
    assert "f2" in fin["state"]["unlocked_fragment_ids"]
    assert fin["newly_unlocked"] == ["f2"]
    # the opening beat lays out the KNOWN evidence; the forced fragment rides new_reveal
    assert "EV_KNOWN" in out["beats"][0]["text"]
    conf = llm.prompts[0]["confrontation"]
    assert conf["outcome"] == "success" and "EV_KNOWN" in conf["evidence"]
    assert any("EV_LOCKED" in r["content"] for r in llm.prompts[0]["context"]["new_reveal"])
    # being cornered costs closeness; the moment + 大事记 land
    assert fin["rel_deltas"]["a"]["closeness"] < 0
    kinds = {m["kind"] for m in fin["moments"]}
    assert "confront" in kinds and "unlock" in kinds
    assert any(e["kind"] == "confront" for e in fin["state"]["rel_log"]["a"])
    # the forced unlock satisfied act 1's gate → the act opens right here
    assert fin["state"]["act"] == 2


def test_failure_reveals_nothing_and_costs_more(monkeypatch):
    monkeypatch.setattr(runtime, "_roll_check",
                        lambda risk: {"risk": risk, "roll": 99, "outcome": "fail"})
    llm = ConfrontLLM()
    st = _ready_state()
    out = _drain(runtime.confront_stream(STORY, st, {"name": "我"}, "f1", "a", llm=llm))
    fin = out["final"]
    assert "f2" not in fin["state"]["unlocked_fragment_ids"]
    assert llm.prompts[0]["context"]["new_reveal"] == []
    assert fin["rel_deltas"]["a"]["closeness"] == -6      # cost ×2, hits the step clamp
    assert fin["state"]["act"] == 1


def test_crit_fail_feeds_pressure_and_crit_success_is_free(monkeypatch):
    monkeypatch.setattr(runtime, "_roll_check",
                        lambda risk: {"risk": risk, "roll": 100, "outcome": "crit_fail"})
    fin = _drain(runtime.confront_stream(STORY, _ready_state(), {"name": "我"}, "f1", "a",
                                         llm=ConfrontLLM()))["final"]
    assert fin["state"]["pressure"] == 8
    assert fin["pressure_view"]["value"] == 8
    monkeypatch.setattr(runtime, "_roll_check",
                        lambda risk: {"risk": risk, "roll": 1, "outcome": "crit_success"})
    fin2 = _drain(runtime.confront_stream(STORY, _ready_state(), {"name": "我"}, "f1", "a",
                                          llm=ConfrontLLM()))["final"]
    assert fin2["rel_deltas"] == {} and "f2" in fin2["state"]["unlocked_fragment_ids"]


def test_closeness_raises_the_odds():
    st = _ready_state()
    st["rel"] = {"a": {"closeness": 60, "romance": 0}}
    rolls = []
    import types
    def fake_roll(risk):
        rolls.append(risk)
        return {"risk": risk, "roll": 99, "outcome": "fail"}
    orig = runtime._roll_check
    runtime._roll_check = fake_roll
    try:
        _drain(runtime.confront_stream(STORY, st, {"name": "我"}, "f1", "a", llm=ConfrontLLM()))
        _drain(runtime.confront_stream(STORY, _ready_state(), {"name": "我"}, "f1", "a",
                                       llm=ConfrontLLM()))
    finally:
        runtime._roll_check = orig
    # base 55 + closeness//2 (fresh relationships start at closeness 5 → 57)
    assert rolls[0] == 85 and rolls[1] == 57


def test_journal_marks_confrontable():
    st = _ready_state()
    st["location_id"] = "hall"
    jd = runtime.journal(STORY, st)
    sec = jd["secrets"][0]
    assert sec["character_id"] == "a" and sec["confrontable"] is True
    assert sec["frags"][0]["id"] == "f1"
    # owner dead → not confrontable; fully unlocked → nothing left to pry
    st2 = _ready_state(); st2["dead_character_ids"] = ["a"]
    assert runtime.journal(STORY, st2)["secrets"][0]["confrontable"] is False
    st3 = _ready_state(); st3["unlocked_fragment_ids"] = ["f1", "f2"]
    assert runtime.journal(STORY, st3)["secrets"][0]["confrontable"] is False
