"""Stuck-hint escalation: while the player is stuck on a gated act (can't find the
required clue), a counter climbs; once it crosses STUCK_PUSH a narrator nudge fires that
openly points at one missing topic — by LABEL only, never the locked fragment body."""

from app.engine import runtime

# f1 is effectively unreachable (sky-high affinity floor) so the act stays locked no matter
# how long the player pokes at it — exactly the "stuck" situation.
STUCK = {
    "story": {
        "id": "st",
        "characters": [{"id": "c1", "name": "Mara", "is_lead": True, "persona_text": "a"}],
        "acts": [
            {"index": 1, "title": "一", "advance": {"required_fragment_ids": ["f1"]}},
            {"index": 2, "title": "二"},
        ],
    },
    "secrets": [{
        "id": "sec1", "character_id": "c1", "title": "那本账",
        "fragments": [{
            "id": "f1", "content": "BODY_SECRET", "retrieval_key": "ledger",
            "known_by_character_ids": ["c1"],
            "unlock": {"affinity_min": 999, "act_min": 1, "asks_min": 99},
        }],
    }],
}


def _play(state):
    return runtime.run_turn(STUCK, state, {"name": "我"}, "随便聊聊天气", channel="say")


def test_stuck_counter_climbs_and_hint_fires():
    # the stuck hint is now a PERSISTENT top-bar string (out["hint"]), not a chat beat
    st = runtime.default_state()
    assert st["stuck"] == 0
    hint_seen_at = None
    for turn in range(1, runtime.STUCK_SPELL + 2):
        out = _play(st)
        st = out["state"]
        assert st["act"] == 1, "gated act must stay locked while clue is unreachable"
        assert st["stuck"] == turn, "every clue-less locked turn bumps the counter"
        # the hint names the missing topic by label
        if "那本账" in (out.get("hint") or ""):
            hint_seen_at = hint_seen_at or turn
    # the hint should have fired no later than the PUSH threshold
    assert hint_seen_at is not None and hint_seen_at <= runtime.STUCK_PUSH

    # and it must steer by topic LABEL only — the locked body never leaks anywhere
    last = _play(st)
    assert "BODY_SECRET" not in " ".join(b.get("text", "") for b in last["beats"])
    assert "BODY_SECRET" not in (last.get("hint") or "")


def test_progress_resets_the_counter():
    # an UNgated act never accrues stuck (nothing to be stuck on)
    open_story = {
        "story": {"id": "s", "characters": [{"id": "c1", "name": "M", "is_lead": True}],
                  "acts": [{"index": 1, "title": "a"}, {"index": 2, "title": "b"}]},
        "secrets": [],
    }
    st = runtime.default_state()
    for _ in range(3):
        st = runtime.run_turn(open_story, st, {"name": "我"}, "聊聊", channel="say")["state"]
        assert st["stuck"] == 0
