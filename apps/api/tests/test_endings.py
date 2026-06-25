"""Tests for the ending/consequence system: a fatal action ends the run immediately,
and authored endings fire at the final act with the best-matching kind winning."""

from app.engine import runtime


class _FixedLLM:
    """Test double: returns whatever director fields the test wants."""

    def __init__(self, **fields):
        self._fields = {"beats": [{"type": "dialogue", "speaker_name": "Mara", "text": "..."}],
                        "affinity_delta": 0, "advance_act": False, "ending": None}
        self._fields.update(fields)

    def generate(self, prompt):
        return dict(self._fields)


CONTENT = {
    "story": {
        "id": "st",
        "characters": [{"id": "c1", "name": "Mara", "is_lead": True}],
        "acts": [{"index": 1, "title": "一", "events": []},
                 {"index": 2, "title": "二", "events": []}],
        "endings": [
            {"id": "e_normal", "kind": "normal", "title": "平淡收场", "text": "天亮了。",
             "condition": {"affinity_min": 0, "act_min": 0}},
            {"id": "e_true", "kind": "true", "title": "真相大白", "text": "你知道了一切。",
             "condition": {"affinity_min": 30, "act_min": 0, "required_fragment_ids": ["f1"]}},
        ],
    },
    "secrets": [],
}


def _persona():
    return {"name": "我"}


def test_fatal_action_ends_run_immediately():
    llm = _FixedLLM(ending={"kind": "death", "reason": "火光吞没了整层楼。"})
    out = runtime.run_turn(CONTENT, runtime.default_state(), _persona(),
                           "我点燃了煤气然后划了根火柴", llm=llm)
    assert out["ending"]["kind"] == "death"
    assert out["state"]["ended"] is True
    # the run is even at act 1 — death doesn't wait for the final act
    assert out["state"]["act"] == 1


def test_no_ending_mid_story_without_fatal_action():
    llm = _FixedLLM()  # no model ending, low affinity, no advance
    out = runtime.run_turn(CONTENT, runtime.default_state(), _persona(), "你好", llm=llm)
    assert out["ending"] is None
    assert not out["state"].get("ended")


def test_normal_ending_is_a_milestone_not_terminal():
    state = {**runtime.default_state(), "act": 2, "affinity": 5}
    llm = _FixedLLM()
    out = runtime.run_turn(CONTENT, state, _persona(), "再见", llm=llm)
    assert out["ending"]["kind"] == "normal"
    # reaching an authored ending does NOT end the run — the open world continues
    assert not out["state"].get("ended")
    assert "e_normal" in out["state"]["achieved_endings"]


def test_true_ending_beats_normal_when_conditions_met():
    # at final act, high affinity AND the key fragment unlocked → true ending wins
    state = {**runtime.default_state(), "act": 2, "affinity": 40,
             "unlocked_fragment_ids": ["f1"]}
    llm = _FixedLLM()
    out = runtime.run_turn(CONTENT, state, _persona(), "我懂了", llm=llm)
    assert out["ending"]["kind"] == "true"
    assert not out["state"].get("ended")  # still explorable


def test_milestone_announced_only_once():
    # first arrival at final act announces normal; a follow-up turn does NOT re-announce
    state = {**runtime.default_state(), "act": 2, "affinity": 5}
    llm = _FixedLLM()
    out1 = runtime.run_turn(CONTENT, state, _persona(), "再见", llm=llm)
    assert out1["ending"] and out1["ending"]["kind"] == "normal"
    out2 = runtime.run_turn(CONTENT, out1["state"], _persona(), "我再看看四周", llm=llm)
    assert out2["ending"] is None  # already achieved, keep exploring quietly


def test_upgrade_from_normal_to_true_when_affinity_grows():
    # reach normal first, then meet the true ending's bar → true fires as a NEW milestone
    state = {**runtime.default_state(), "act": 2, "affinity": 5}
    llm = _FixedLLM()
    s1 = runtime.run_turn(CONTENT, state, _persona(), "再见", llm=llm)["state"]
    s1["affinity"] = 40
    s1["unlocked_fragment_ids"] = ["f1"]
    out = runtime.run_turn(CONTENT, s1, _persona(), "我终于懂了", llm=llm)
    assert out["ending"]["kind"] == "true"
