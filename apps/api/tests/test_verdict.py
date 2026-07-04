"""🔍 指认结案: ask anything all game, but the case ends with a FORMAL, limited-attempt
commitment. Correct sets verdict_solved (真结局 gates on it); the last wrong attempt
fires the authored fail ending. The panel never leaks which option is right."""

import pytest

from app.engine import logic, runtime

STORY = {
    "story": {"id": "s",
              "characters": [{"id": "a", "name": "甲", "is_lead": True}],
              "acts": [{"index": 1, "title": "一"}, {"index": 2, "title": "二"}],
              "endings": [
                  {"id": "end_true", "kind": "true", "title": "真",
                   "condition": {"act_min": 2, "required_flags": {"verdict_solved": True}}},
                  {"id": "end_wrong", "kind": "bad", "trigger": "verdict", "title": "错判",
                   "text": "你指错了。", "condition": {}},
              ],
              "verdict": {"prompt": "第六个人是谁？", "attempts": 2, "act_min": 2,
                          "fail_ending_id": "end_wrong",
                          "options": [
                              {"id": "v1", "label": "是甲", "correct": True, "text": "他点了点头。"},
                              {"id": "v2", "label": "是乙"},
                              {"id": "v3", "label": "没有第六个人"},
                          ]}},
    "secrets": [],
}


def test_view_gates_by_act_and_never_leaks():
    st = runtime.default_state()
    assert runtime.verdict_view(STORY, st) is None            # act 1 < act_min 2
    st["act"] = 2
    v = runtime.verdict_view(STORY, st)
    assert v["attempts_left"] == 2 and len(v["options"]) == 3
    assert "correct" not in str(v)                            # the answer never leaves
    st["mode"] = "god"
    assert runtime.verdict_view(STORY, st) is None            # observers don't testify


def test_correct_call_sets_the_flag_and_opens_the_true_ending():
    st = runtime.default_state()
    st["act"] = 2
    res = runtime.submit_verdict(STORY, st, "v1")
    assert res["correct"] is True and "点了点头" in res["text"]
    assert st["flags"]["verdict_solved"] is True
    assert runtime.evaluate_ending(STORY, st, None)["id"] == "end_true"
    # solved = closed; no double jeopardy
    with pytest.raises(ValueError, match="案子结了"):
        runtime.submit_verdict(STORY, st, "v2")
    # first-try hit earns the achievement
    assert any(a["id"] == "sharp_eye" for a in runtime.compute_achievements(
        {**STORY}, {**st, "achieved_endings": ["end_true"]}))


def test_wrong_calls_burn_attempts_then_fire_the_fail_ending():
    st = runtime.default_state()
    st["act"] = 2
    r1 = runtime.submit_verdict(STORY, st, "v2")
    assert r1["correct"] is False and r1["attempts_left"] == 1 and r1["ending"] is None
    with pytest.raises(ValueError, match="已经指认过"):
        runtime.submit_verdict(STORY, st, "v2")               # same guess twice refused
    r2 = runtime.submit_verdict(STORY, st, "v3")
    assert r2["ending"] and r2["ending"]["id"] == "end_wrong" and not r2["ending"]["terminal"]
    assert "end_wrong" in st["achieved_endings"] and st["verdict_failed"] is True
    with pytest.raises(ValueError, match="机会用完了"):
        runtime.submit_verdict(STORY, st, "v1")
    # without verdict_solved the true ending stays out of reach
    assert (runtime.evaluate_ending(STORY, st, None) or {}).get("id") != "end_true"
    # tried options surface so the UI can strike them out
    v = runtime.verdict_view(STORY, st)
    assert v["tried"] == ["v2", "v3"] and v["failed"] is True


def test_linter_checks_verdict_shape():
    bad = {"story": {**STORY["story"],
                     "verdict": {"prompt": "?", "fail_ending_id": "nope",
                                 "options": [{"id": "x", "label": "a"},
                                             {"id": "x", "label": "b"}]},
                     "endings": [{"id": "e1", "kind": "normal", "title": "t",
                                  "condition": {}}]},
           "secrets": []}
    codes = {i["code"] for i in logic.lint_story(bad)}
    assert {"verdict_no_answer", "verdict_bad_options",
            "verdict_bad_ending", "verdict_ungated"} <= codes
