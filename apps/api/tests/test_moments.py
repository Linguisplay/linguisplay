"""Threshold moments (阈值时刻演出): unlock / relationship tier-up / act advance / ending
milestones surface as structured `moments` (+ per-char rel_deltas) for the UI to celebrate."""

from app.engine import runtime

STORY = {
    "story": {"id": "s",
              "tuning": {"friend_t": 6, "close_step_max": 8},  # tier-up reachable in one turn
              "characters": [{"id": "c1", "name": "M", "is_lead": True}],
              "acts": [{"index": 1, "title": "一"}, {"index": 2, "title": "二"}]},
    "secrets": [{"id": "s1", "character_id": "c1", "title": "那本账",
                 "fragments": [{"id": "f1", "content": "BODY", "retrieval_key": "k",
                                "known_by_character_ids": ["c1"],
                                "unlock": {"asks_min": 1}}]}],
}


class WarmLLM:
    def generate(self, prompt):
        if prompt.get("intro") or prompt.get("observe") or prompt.get("suggest"):
            return {"beats": [{"type": "description", "speaker_name": None, "text": "x"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}
        return {"beats": [{"type": "dialogue", "speaker_name": prompt.get("speaker_name"), "text": "嗯"}],
                "affinity_delta": 5, "romance_delta": 0, "advance_act": True, "ending": None}


def test_unlock_relup_and_act_moments_fire_with_deltas():
    st = runtime.default_state()
    # probing unlocks f1 (asks_min=1) + warm delta crosses the tuned friend_t + model advances act
    out = runtime.run_turn(STORY, st, {"name": "我"}, "跟我说说那本账", channel="say",
                           llm=WarmLLM())
    kinds = {m["kind"] for m in out["moments"]}
    assert "unlock" in kinds
    assert any(m["kind"] == "unlock" and m["title"] == "那本账" for m in out["moments"])
    assert "rel_up" in kinds                      # stranger → friend at closeness 5+5 ≥ 6
    assert "act" in kinds                         # model 推进 on an ungated act
    d = out["rel_deltas"].get("c1")
    assert d and d["closeness"] == 5              # the per-char ♥ float payload
    # moments carry titles/labels only — never locked bodies
    assert "BODY" not in str(out["moments"])


def test_quiet_turn_has_no_moments():
    story = {"story": {"id": "s2", "characters": [{"id": "c1", "name": "M", "is_lead": True}],
                       "acts": [{"index": 1, "title": "一"}]}, "secrets": []}
    st = runtime.default_state()
    out = runtime.run_turn(story, st, {"name": "我"}, "你好", channel="say")  # MockLLM
    assert out["moments"] == []
