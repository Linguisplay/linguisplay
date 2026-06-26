"""Hard progression gate: an act with authored advance conditions does NOT advance until
the required clue is actually unlocked (program-checked, not model/affinity). Acts without
conditions keep the old soft advance."""

from app.engine import runtime

GATED = {
    "story": {
        "id": "st",
        "characters": [{"id": "c1", "name": "Mara", "is_lead": True, "persona_text": "a"}],
        "acts": [
            {"index": 1, "title": "一", "advance": {"required_fragment_ids": ["f1"]}},
            {"index": 2, "title": "二"},
        ],
    },
    "secrets": [{
        "id": "sec1", "character_id": "c1", "title": "账本",
        "fragments": [{
            "id": "f1", "content": "BODY", "retrieval_key": "ledger 账本",
            "known_by_character_ids": ["c1"],
            "unlock": {"affinity_min": 6, "act_min": 1, "asks_min": 2},
        }],
    }],
}


def _play(state, text):
    return runtime.run_turn(GATED, state, {"name": "我"}, text, channel="say")


def test_gated_act_blocks_until_clue_found():
    o1 = _play(runtime.default_state(), "问问 账本")   # asks1, affinity rising
    assert o1["state"]["act"] == 1
    assert o1["progress"]["total"] == 1 and o1["progress"]["done"] == 0

    o2 = _play(o1["state"], "再追 账本")               # asks2, but affinity floor not yet met
    assert o2["state"]["act"] == 1

    # o2's checklist (still act 1) shows the clue still missing
    assert o2["progress"]["total"] == 1 and o2["progress"]["done"] == 0

    o3 = _play(o2["state"], "继续逼问 账本")           # affinity floor met now → f1 unlocks → advance
    assert "f1" in o3["state"]["unlocked_fragment_ids"]
    assert o3["state"]["act"] == 2
    assert o3["progress"]["total"] == 0  # advanced into act 2, which has no gate


def test_can_advance_pure_function():
    locked = {**runtime.default_state(), "act": 1, "unlocked_fragment_ids": []}
    assert runtime.can_advance(GATED, locked, 1) is False
    unlocked = {**runtime.default_state(), "act": 1, "unlocked_fragment_ids": ["f1"]}
    assert runtime.can_advance(GATED, unlocked, 1) is True


def test_ungated_act_still_soft_advances():
    ungated = {
        "story": {"id": "s", "characters": [{"id": "c1", "name": "M", "is_lead": True}],
                  "acts": [{"index": 1, "title": "a"}, {"index": 2, "title": "b"}, {"index": 3, "title": "c"}]},
        "secrets": [],
    }
    st = runtime.default_state()
    for _ in range(6):  # MockLLM +3 affinity/turn → backstop 1+affinity//12 advances
        st = runtime.run_turn(ungated, st, {"name": "我"}, "hi")["state"]
    assert st["act"] >= 2
