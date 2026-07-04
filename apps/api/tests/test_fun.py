"""The fun layer: 🎲 fate rolls on risky 做-actions, ⚠️ the story pressure meter
(level notes → blowout ending), and 🌊 the world moving by itself (paced authored
events firing without the player causing them)."""

import random

from app.engine import runtime

BASE = {
    "story": {"id": "s", "characters": [{"id": "c1", "name": "M", "is_lead": True}],
              "acts": [{"index": 1, "title": "一",
                        "events": [{"id": "ev1", "what_happens": "远处传来一声闷响。"}]},
                       {"index": 2, "title": "二"}]},
    "secrets": [],
}

PRESSURED = {
    "story": {**BASE["story"],
              "pressure": {"name": "暴露风险", "hint": "出格会推高",
                           "ending_id": "end_x",
                           "levels": [{"at": 30, "note": "有人开始留意你。"}]},
              "endings": [{"id": "end_x", "kind": "death", "trigger": "pressure",
                           "title": "败露", "text": "一切都结束了。", "condition": {}}]},
    "secrets": [],
}


class FunLLM:
    """Configurable: risk for the judge call, pressure delta for the director."""

    def __init__(self, risk=100, pressure=None):
        self.risk = risk
        self.pressure = pressure
        self.prompts = []

    def generate(self, prompt):
        if prompt.get("risk_judge"):
            return {"risk": self.risk}
        if prompt.get("intro") or prompt.get("observe") or prompt.get("suggest"):
            return {"beats": [{"type": "description", "speaker_name": None, "text": "x"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}
        self.prompts.append(prompt)
        out = {"beats": [{"type": "dialogue", "speaker_name": prompt.get("speaker_name"), "text": "嗯"}],
               "affinity_delta": 0, "advance_act": False, "ending": None}
        if self.pressure is not None:
            out["pressure_delta"] = self.pressure
        return out


def test_roll_check_mapping():
    class FixedRng:
        def __init__(self, v):
            self.v = v

        def randint(self, a, b):
            assert (a, b) == (1, 20)              # the fate die is a d20 now
            return self.v

    # risk 60% → 12 of 20 faces succeed → DC 9; nat 20/1 override everything
    for v, want in ((20, "crit_success"), (1, "crit_fail"), (9, "success"), (8, "fail")):
        runtime._rng = FixedRng(v)
        d = runtime._roll_check(60)
        assert d["dc"] == 9 and d["die"] == 20 and d["outcome"] == want
    # near-impossible: only the natural 20 lands it
    runtime._rng = FixedRng(19)
    assert runtime._roll_check(1)["outcome"] == "fail"
    runtime._rng = FixedRng(20)
    assert runtime._roll_check(1)["outcome"] == "crit_success"
    # a real sequence shows the full spread
    runtime._rng = random.Random(7)
    seen = {runtime._roll_check(60)["outcome"] for _ in range(300)}
    assert seen == {"crit_success", "success", "fail", "crit_fail"}


def test_risky_do_action_rolls_and_briefs_the_director():
    runtime._rng = random.Random(1)
    llm = FunLLM(risk=55)
    out = runtime.run_turn(BASE, runtime.default_state(), {"name": "我"}, "我翻墙进去",
                           channel="do", llm=llm)
    d = out["dice"]
    assert d and d["risk"] == 55 and 1 <= d["roll"] <= 20 and d["die"] == 20
    assert 2 <= d["dc"] <= 20
    assert llm.prompts[0].get("check") == d          # the director must narrate the result


def test_no_dice_when_mundane_or_disabled_or_talking():
    llm = FunLLM(risk=100)
    out = runtime.run_turn(BASE, runtime.default_state(), {"name": "我"}, "我坐下", channel="do", llm=llm)
    assert out["dice"] is None                       # judge says mundane
    out2 = runtime.run_turn(BASE, runtime.default_state(), {"name": "我"}, "我翻墙", channel="say",
                            llm=FunLLM(risk=10))
    assert out2["dice"] is None                      # 说 never rolls
    off = {"story": {**BASE["story"], "tuning": {"dice": 0}}, "secrets": []}
    out3 = runtime.run_turn(off, runtime.default_state(), {"name": "我"}, "我翻墙", channel="do",
                            llm=FunLLM(risk=10))
    assert out3["dice"] is None                      # story opted out


def test_pressure_accumulates_announces_levels():
    llm = FunLLM(pressure=20)
    st = runtime.default_state()
    out = runtime.run_turn(PRESSURED, st, {"name": "我"}, "我是警察！", channel="say", llm=llm)
    assert out["state"]["pressure"] == 20
    assert out["pressure_view"] == {"name": "暴露风险", "value": 20}
    out2 = runtime.run_turn(PRESSURED, out["state"], {"name": "我"}, "快说！", channel="say", llm=llm)
    assert out2["state"]["pressure"] == 40           # crossed 30 → the level note fires
    assert any("有人开始留意你" in b.get("text", "") for b in out2["beats"])
    assert any(m["kind"] == "pressure" for m in out2["moments"])


def test_pressure_blowout_forces_the_terminal_ending():
    llm = FunLLM(pressure=15)
    st = {**runtime.default_state(), "pressure": 90}
    out = runtime.run_turn(PRESSURED, st, {"name": "我"}, "都听我说！", channel="say", llm=llm)
    assert out["state"]["pressure"] == 100
    assert out["state"]["ended"] is True
    assert out["ending"] and out["ending"]["id"] == "end_x" and out["ending"]["terminal"]
    texts = " ".join(b.get("text", "") for b in out["beats"])
    assert "败露" in texts


def test_world_moves_by_itself_after_quiet_turns():
    st = runtime.default_state()
    fired_at = None
    for turn in range(1, 6):
        out = runtime.run_turn(BASE, st, {"name": "我"}, "随便聊聊", channel="say")  # MockLLM
        st = out["state"]
        if any("就在这时，远处传来一声闷响" in b.get("text", "") for b in out["beats"]):
            fired_at = fired_at or turn
    assert fired_at == 4                             # default world_event_every = 4
    assert "ev1" in st["triggered_event_ids"]
    assert st["world_pulse"] == 1                    # reset at the impulse, +1 on the quiet 5th turn


def test_world_impulse_respects_who_is_present():
    story = {"story": {**BASE["story"],
                       "acts": [{"index": 1, "title": "一",
                                 "events": [{"id": "ev2", "what_happens": "神秘人推门而入。",
                                             "who_character_ids": ["ghost"]}]}]},
             "secrets": []}
    st = runtime.default_state()
    for _ in range(6):
        out = runtime.run_turn(story, st, {"name": "我"}, "聊聊", channel="say")
        st = out["state"]
    assert "ev2" not in st["triggered_event_ids"]    # its character isn't in the scene
