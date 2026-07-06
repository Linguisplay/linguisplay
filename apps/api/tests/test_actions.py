"""🎲 行动解算: the engine classifies a 做-attempt (verb class → base tier → state
modifiers → DC); classified actions ALWAYS roll — the model only nudges ±1 tier."""

from app.engine import actions, runtime

STORY = {
    "story": {
        "id": "ac",
        "characters": [{"id": "c1", "name": "守卫", "home_location_id": "l1"}],
        "acts": [{"index": 1, "title": "一"}],
        "locations": [{"id": "l1", "name": "库房", "detail": "一把铁锁", "exits": []}],
    },
    "secrets": [],
}


def test_classify_tiers_and_modifiers():
    st = runtime.default_state()
    a = actions.classify(STORY, st, "我偷偷溜进后院顺走那串钥匙")
    assert a and a["cls"] == "潜行" and a["tier"] == "hard" and a["dc"] == 15
    # wounds raise the bar; a fitting tool lowers it
    st2 = {**runtime.default_state(), "player_hp": "hurt",
           "inventory": [{"name": "撬棍"}]}
    b = actions.classify(STORY, st2, "用撬棍撬开库房的铁锁")
    assert b and b["cls"] == "破闯" and b["dc"] == 15 + 2 - 2
    # plain speech / unclassified stunts stay off this path
    assert actions.classify(STORY, st, "跟守卫聊聊天") is None
    assert actions.classify(STORY, st, "打开窗户透透气") is None  # 打开≠强攻


def test_model_opinion_moves_at_most_one_tier():
    base = {"cls": "破闯", "tier": "hard", "dc": 15, "mods": []}
    assert actions.resolve_dc(base, 90)["tier"] == "normal"    # model says easy → clamp to normal
    assert actions.resolve_dc(base, 10)["tier"] == "extreme"   # model says极难 → one step up
    assert actions.resolve_dc(base, 100)["tier"] == "hard"     # model saw no risk → base stands
    assert actions.resolve_dc(base, None)["adjusted"] is False


def test_classified_action_always_rolls_even_if_model_says_safe():
    st = {**runtime.default_state(), "location_id": "l1"}

    class SafeLLM:
        def generate(self, prompt):
            if prompt.get("risk_judge"):
                return {"risk": 100}     # the old no-roll veto — no longer honored
            if any(prompt.get(k) for k in ("suggest", "arrive", "offscreen", "farewell",
                                           "summarize", "golden_moment")):
                return {}
            return {"beats": [{"type": "description", "speaker_name": None, "text": "咔。"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None,
                    "next_speakers": []}

    out = runtime.run_turn(STORY, st, {"name": "我"}, "我撬开库房的铁锁", channel="do",
                           llm=SafeLLM())
    assert out.get("dice") and out["dice"]["dc"] == 15
    assert any(e["e"] == "check" and "破闯" in e.get("data", "") for e in out["audit"])
    # …while an unclassified action with risk=100 still doesn't roll (legacy path intact)
    out2 = runtime.run_turn(STORY, st, {"name": "我"}, "把窗台上的花摆正", channel="do",
                            llm=SafeLLM())
    assert out2.get("dice") is None
