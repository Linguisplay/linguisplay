"""✨ 金手指 as higher law: invoking a declared power never rolls dice, the digest
flags it at depth-0, and a turn that tries to suppress it gets rewritten."""

from app.engine import intent, runtime

STORY = {
    "story": {
        "id": "pw",
        "characters": [{"id": "c1", "name": "卫兵", "home_location_id": "l1"}],
        "acts": [{"index": 1, "title": "一"}],
        "locations": [{"id": "l1", "name": "城门", "detail": "铁闸", "exits": []}],
    },
    "secrets": [],
}
POWERS = ["状态之眼：看穿他人状态与好感", "雷霆一击：召下一道真实的落雷"]


def _st():
    return {**runtime.default_state(), "location_id": "l1", "powers": list(POWERS)}


def test_power_name_detection_and_digest():
    st = _st()
    assert runtime._power_named(st, "我用状态之眼看看他") == "状态之眼"
    assert runtime._power_named(st, "我瞪了他一眼") == ""
    d = intent.digest(intent.analyze(STORY, st, "用状态之眼扫他", "do"))
    assert "动用金手指" in d and "必须无条件完整生效" in d


def test_invoking_a_power_never_rolls_dice():
    st = _st()

    class RiskyLLM:
        def __init__(self):
            self.risk_called = False

        def generate(self, prompt):
            if prompt.get("risk_judge"):
                self.risk_called = True
                return {"risk": 30}   # would normally trigger a roll
            if any(prompt.get(k) for k in ("suggest", "arrive", "offscreen", "farewell",
                                           "summarize", "golden_moment")):
                return {}
            return {"beats": [{"type": "description", "speaker_name": None, "text": "雷落了。"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None,
                    "next_speakers": []}

    llm = RiskyLLM()
    out = runtime.run_turn(STORY, st, {"name": "我"}, "我发动雷霆一击劈向铁闸", channel="do",
                           llm=llm)
    assert llm.risk_called is False and out.get("dice") is None
    assert any(e["e"] == "power" and e["ok"] for e in out["audit"])


def test_suppressing_an_invoked_power_is_a_violation():
    st = _st()
    prompt = {"player_input": "我用状态之眼看穿卫兵"}
    bad = {"beats": [{"type": "description", "text": "一股无形之力让你的能力失灵了。"}]}
    good = {"beats": [{"type": "dialogue", "text": "卫兵的心事在你眼前摊开。"}]}
    assert runtime._power_break(prompt, bad, st) is True
    assert runtime._power_break(prompt, good, st) is False
    # not invoked → suppression words are ordinary prose, no violation
    assert runtime._power_break({"player_input": "你怎么了"}, bad, st) is False
