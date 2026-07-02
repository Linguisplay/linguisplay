"""Key-moment VN choices: an act's authored decision pends on act entry, resolves
deterministically (flags / 好感 / relationship deltas), answers only once, and its flag
feeds ending conditions (choice → flag → ending chain)."""

from app.engine import runtime

STORY = {
    "story": {
        "id": "s",
        "tuning": {"min_turns_per_act": 0},   # this test drives the act by hand
        "characters": [{"id": "c1", "name": "M", "is_lead": True}],
        "acts": [
            {"index": 1, "title": "一"},
            {"index": 2, "title": "二",
             "choice": {"prompt": "站哪边？",
                        "options": [
                            {"id": "a", "label": "站他们那边", "flag": "sided",
                             "affinity_delta": 2, "character_id": "c1", "closeness_delta": 5},
                            {"id": "b", "label": "按章办事", "flag": "obeyed"},
                        ]}},
        ],
        "endings": [
            {"id": "e1", "kind": "true", "title": "同路人",
             "condition": {"affinity_min": 0, "act_min": 2, "required_flags": {"sided": True}}},
        ],
    },
    "secrets": [],
}


class AdvanceLLM:
    def generate(self, prompt):
        if prompt.get("intro") or prompt.get("observe") or prompt.get("suggest"):
            return {"beats": [{"type": "description", "speaker_name": None, "text": "x"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}
        return {"beats": [{"type": "dialogue", "speaker_name": prompt.get("speaker_name"), "text": "嗯"}],
                "affinity_delta": 0, "advance_act": True, "ending": None}


def _enter_act2():
    st = runtime.default_state()
    out = runtime.run_turn(STORY, st, {"name": "我"}, "走吧", channel="say", llm=AdvanceLLM())
    assert out["state"]["act"] == 2
    return out


def test_choice_pends_on_act_entry_without_effects_leaking():
    out = _enter_act2()
    ch = out["pending_choice"]
    assert ch and ch["prompt"] == "站哪边？"
    assert [o["id"] for o in ch["options"]] == ["a", "b"]
    # player-facing shape carries labels only — no effects/flags exposed
    assert "flag" not in ch["options"][0] and "closeness_delta" not in str(ch["options"])


def test_apply_choice_effects_and_once_only():
    st = _enter_act2()["state"]
    res = runtime.apply_choice(STORY, st, "a")
    assert res["label"] == "站他们那边"
    assert st["flags"].get("sided") is True
    assert st["affinity"] == 2
    assert st["rel"]["c1"]["closeness"] == runtime.relationships.new_scores()["closeness"] + 5
    assert st["pending_choice"] is None
    assert st["choices"] == {"act2": "a"}
    # answered → no re-pend on the same act, and answering again fails
    assert runtime.choice_for_act(STORY, st, 2) is None
    try:
        runtime.apply_choice(STORY, st, "b")
        assert False, "second answer must be rejected"
    except ValueError:
        pass


def test_choice_flag_gates_the_ending():
    st = _enter_act2()["state"]
    # without the flag, the flag-gated true ending is not eligible at the final act
    assert runtime.evaluate_ending(STORY, st, None) is None
    runtime.apply_choice(STORY, st, "a")
    fired = runtime.evaluate_ending(STORY, st, None)
    assert fired and fired["id"] == "e1" and fired["kind"] == "true"


def test_unknown_option_rejected():
    st = _enter_act2()["state"]
    try:
        runtime.apply_choice(STORY, st, "nope")
        assert False
    except ValueError as e:
        assert "unknown option" in str(e)
