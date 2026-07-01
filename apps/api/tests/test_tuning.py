"""Per-story pacing/balance knobs: story.tuning overrides engine defaults (unknown keys
and junk values ignored), and the overrides actually change engine behavior."""

from app.engine import relationships, runtime


def test_tuning_for_merges_and_sanitizes():
    content = {"story": {"tuning": {"friend_t": 20, "bogus_key": 1, "flirt_t": "junk"}}}
    t = runtime.tuning_for(content)
    assert t["friend_t"] == 20                       # authored override wins
    assert t["flirt_t"] == runtime.DEFAULT_TUNING["flirt_t"]  # junk value ignored
    assert "bogus_key" not in t                      # unknown key ignored
    # no tuning at all → pure defaults
    assert runtime.tuning_for({"story": {}}) == runtime.DEFAULT_TUNING


def test_relationship_thresholds_respect_tuning():
    char = {"id": "c1", "name": "M"}  # default: all modes allowed
    scores = {"closeness": 25, "romance": 0}
    assert relationships.derive_mode(char, scores) == "stranger"      # default friend_t=40
    assert relationships.derive_mode(char, scores, {"friend_t": 20}) == "friend"
    # step clamp override: a +8 delta is cut to +2
    out = relationships.apply_deltas({"closeness": 0, "romance": 0}, 8, 0,
                                     {"close_step_max": 2})
    assert out["closeness"] == 2


def test_stuck_hint_threshold_tunable():
    story = {
        "story": {"id": "st", "tuning": {"stuck_push": 1},
                  "characters": [{"id": "c1", "name": "M", "is_lead": True}],
                  "acts": [{"index": 1, "title": "一", "advance": {"required_fragment_ids": ["f1"]}},
                           {"index": 2, "title": "二"}]},
        "secrets": [{"id": "s1", "character_id": "c1", "title": "谜团",
                     "fragments": [{"id": "f1", "content": "X", "retrieval_key": "k",
                                    "known_by_character_ids": ["c1"],
                                    "unlock": {"affinity_min": 999}}]}],
    }
    st = runtime.default_state()
    out = runtime.run_turn(story, st, {"name": "我"}, "聊聊天气", channel="say")
    # default stuck_push is 2 (no hint on turn 1); tuned to 1 → hint fires immediately
    assert "谜团" in (out.get("hint") or "")


def test_affinity_clamp_tunable():
    story = {"story": {"id": "s", "tuning": {"affinity_clamp_max": 2},
                       "characters": [{"id": "c1", "name": "M", "is_lead": True}],
                       "acts": [{"index": 1, "title": "a"}]}, "secrets": []}

    class WarmLLM:
        def generate(self, prompt):
            if prompt.get("intro") or prompt.get("observe") or prompt.get("suggest"):
                return {"beats": [{"type": "description", "speaker_name": None, "text": "x"}],
                        "affinity_delta": 0, "advance_act": False, "ending": None}
            return {"beats": [{"type": "dialogue", "speaker_name": prompt.get("speaker_name"), "text": "嗯"}],
                    "affinity_delta": 8, "advance_act": False, "ending": None}

    st = runtime.default_state()
    out = runtime.run_turn(story, st, {"name": "我"}, "你好", channel="say", llm=WarmLLM())
    assert out["state"]["affinity"] == 2  # +8 model delta clamped to the story's +2 ceiling
