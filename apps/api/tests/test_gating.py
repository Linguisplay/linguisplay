"""Unit tests for the gating core — the security boundary. If these pass, locked
fragment content cannot reach the LLM context regardless of run state."""

from app.engine import gating

CONTENT = {
    "story": {"id": "st", "characters": [{"id": "c1", "name": "Mara", "is_lead": True}]},
    "secrets": [
        {
            "id": "sec1",
            "character_id": "c1",
            "title": "The hidden ledger",
            "fragments": [
                {
                    "id": "f1",
                    "content": "SECRET_BODY_40K",
                    "retrieval_key": "ledger numbers",
                    "known_by_character_ids": ["c1"],
                    "unlock": {"affinity_min": 3, "act_min": 1, "asks_min": 2},
                }
            ],
        }
    ],
}

FRAGS = gating.iter_fragments(CONTENT)


def _state(**kw):
    base = {"act": 1, "affinity": 0, "asks": {}, "unlocked_fragment_ids": [], "triggered_event_ids": []}
    base.update(kw)
    return base


def test_locked_when_no_conditions_met():
    assert gating.evaluate_unlocks(_state(), FRAGS) == []
    ctx = gating.build_context("c1", FRAGS, _state())
    assert ctx["reveal"] == []
    assert "SECRET_BODY_40K" not in str(ctx)  # the invariant


def test_all_conditions_anded():
    # affinity + act ok but asks short → still locked
    s = _state(affinity=5, act=2, asks={"sec1": 1})
    assert gating.evaluate_unlocks(s, FRAGS) == []
    # all met → unlocks
    s = _state(affinity=3, act=1, asks={"sec1": 2})
    assert gating.evaluate_unlocks(s, FRAGS) == ["f1"]


def test_reveal_exposes_content_only_when_unlocked():
    s = _state(affinity=3, asks={"sec1": 2}, unlocked_fragment_ids=["f1"])
    ctx = gating.build_context("c1", FRAGS, s)
    assert any("SECRET_BODY_40K" in r["content"] for r in ctx["reveal"])


def test_hint_when_one_condition_short_carries_topic_not_body():
    # asks short by one, others met → hint
    s = _state(affinity=3, act=1, asks={"sec1": 1})
    assert gating.classify_guard(FRAGS[0], s) == "hint"
    ctx = gating.build_context("c1", FRAGS, s)
    assert ctx["hint_topics"] == ["The hidden ledger"]
    assert "SECRET_BODY_40K" not in str(ctx)


def test_hide_when_far_from_unlock():
    s = _state(affinity=0, act=1, asks={})  # two conditions short
    assert gating.classify_guard(FRAGS[0], s) == "hide"
    ctx = gating.build_context("c1", FRAGS, s)
    assert ctx["has_hidden"] is True
    assert "SECRET_BODY_40K" not in str(ctx)


def test_known_by_filter_blocks_wrong_speaker():
    s = _state(affinity=3, asks={"sec1": 2}, unlocked_fragment_ids=["f1"])
    # a different speaker who does NOT know it gets nothing, even though unlocked
    ctx = gating.build_context("c2", FRAGS, s)
    assert ctx["reveal"] == []
    assert "SECRET_BODY_40K" not in str(ctx)


def test_unlock_is_sticky_via_union_in_runtime():
    # gating itself only reports NEW unlocks; already-unlocked are excluded
    s = _state(affinity=3, asks={"sec1": 2}, unlocked_fragment_ids=["f1"])
    assert gating.evaluate_unlocks(s, FRAGS) == []
