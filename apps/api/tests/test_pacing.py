"""Pacing brakes (推进太快 fix): affinity/relationship gains taper as they climb,
soft acts require dwell time before ANY advance, and a turn moves at most one act."""

from app.engine import relationships, runtime

SOFT = {
    "story": {"id": "s", "tuning": {"rel_events": 0}, "characters": [{"id": "c1", "name": "M", "is_lead": True}],
              "acts": [{"index": 1, "title": "一"}, {"index": 2, "title": "二"},
                       {"index": 3, "title": "三"}]},
    "secrets": [],
}


class EagerLLM:
    """Wants to advance every single turn with maximum warmth."""

    def generate(self, prompt):
        if prompt.get("intro") or prompt.get("observe") or prompt.get("suggest"):
            return {"beats": [{"type": "description", "speaker_name": None, "text": "x"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}
        return {"beats": [{"type": "dialogue", "speaker_name": prompt.get("speaker_name"), "text": "嗯"}],
                "affinity_delta": 8, "advance_act": True, "ending": None}


def test_soft_act_waits_out_min_turns_despite_eager_model():
    st = runtime.default_state()
    acts = []
    for _ in range(8):
        out = runtime.run_turn(SOFT, st, {"name": "我"}, "聊", channel="say", llm=EagerLLM())
        st = out["state"]
        acts.append(st["act"])
    # default min_turns_per_act=6 → the first five turns stay in act 1, turn 6 advances,
    # and the counter resets so act 3 must be waited out again (one act per turn, ever)
    assert acts[:5] == [1, 1, 1, 1, 1]
    assert acts[5] == 2
    assert max(acts) == 2                     # no multi-act jump within the window


def test_affinity_gains_taper_as_warmth_climbs():
    st = runtime.default_state()
    out = runtime.run_turn(SOFT, st, {"name": "我"}, "聊", channel="say", llm=EagerLLM())
    first_gain = out["state"]["affinity"]     # +8 at affinity 0 → scale 1.0 → 8
    assert first_gain == 8
    st2 = {**runtime.default_state(), "affinity": 80}
    out2 = runtime.run_turn(SOFT, st2, {"name": "我"}, "聊", channel="say", llm=EagerLLM())
    assert out2["state"]["affinity"] - 80 <= 3   # 80/100 → scale 0.3 → +8 becomes ~+2
    assert out2["state"]["affinity"] > 80        # but never fully zero — motion still felt


def test_relationship_gains_taper_but_losses_do_not():
    low = relationships.apply_deltas({"closeness": 0, "romance": 0}, 8, 6)
    high = relationships.apply_deltas({"closeness": 90, "romance": 80}, 8, 6)
    assert low["closeness"] - 0 == 8
    assert high["closeness"] - 90 <= 3           # taper bites near the top
    drop = relationships.apply_deltas({"closeness": 90, "romance": 0}, -6, 0)
    assert drop["closeness"] == 84               # losses stay full-force


def test_hard_gated_acts_unaffected_by_dwell_time():
    gated = {
        "story": {"id": "g", "characters": [{"id": "c1", "name": "M", "is_lead": True}],
                  "acts": [{"index": 1, "title": "一",
                            "advance": {"required_fragment_ids": ["f1"]}},
                           {"index": 2, "title": "二"}]},
        "secrets": [{"id": "s1", "character_id": "c1", "title": "钥匙",
                     "fragments": [{"id": "f1", "content": "X", "retrieval_key": "钥匙",
                                    "unlock": {"asks_min": 1}}]}],
    }
    st = runtime.default_state()
    out = runtime.run_turn(gated, st, {"name": "我"}, "跟我说说钥匙", channel="say")
    assert out["state"]["act"] == 2              # clue found → gate opens turn 1, no dwell wait
