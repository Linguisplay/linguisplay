# -*- coding: utf-8 -*-
"""📸 时刻卡回忆册: album entries carry rarity + the place they were born in, and the
new keepsake triggers land on the shelf — a layered secret assembled, a natural-20
roll, a major breakthrough. Single-fragment secrets don't count as "assembled"."""
from app.engine import runtime

TWO_PIECE = {
    "story": {
        "id": "al",
        "characters": [{"id": "c1", "name": "Mara", "is_lead": True, "persona_text": "a"}],
        "acts": [{"index": 1, "title": "一"}],
        "locations": [{"id": "l1", "name": "书房", "detail": "一间书房", "exits": []}],
    },
    "secrets": [{
        "id": "sec1", "character_id": "c1", "title": "账本",
        "fragments": [
            {"id": "f1", "content": "BODY1", "retrieval_key": "ledger 账本",
             "known_by_character_ids": ["c1"],
             "unlock": {"affinity_min": 0, "act_min": 1, "asks_min": 1}},
            {"id": "f2", "content": "BODY2", "retrieval_key": "ledger 账本",
             "known_by_character_ids": ["c1"],
             "unlock": {"affinity_min": 0, "act_min": 1, "asks_min": 2}},
        ],
    }],
}

ONE_PIECE = {
    "story": TWO_PIECE["story"],
    "secrets": [{
        "id": "sec1", "character_id": "c1", "title": "账本",
        "fragments": [
            {"id": "f1", "content": "BODY1", "retrieval_key": "ledger 账本",
             "known_by_character_ids": ["c1"],
             "unlock": {"affinity_min": 0, "act_min": 1, "asks_min": 1}},
        ],
    }],
}

CULT = {
    "story": {
        "id": "cx", "sandbox": {"enabled": True,
                                "progression": {"name": "斗气",
                                                "ranks": ["斗之气", "斗者", "斗师"]}},
        "characters": [{"id": "c1", "name": "Mara", "is_lead": True, "persona_text": "a"}],
        "acts": [{"index": 1}],
        "locations": [{"id": "l1", "name": "静室", "detail": "一间寻常静室", "exits": []}],
    },
    "secrets": [],
}


def _play(content, state, text, channel="say"):
    return runtime.run_turn(content, state, {"name": "我"}, text, channel=channel)


def _kinds(state):
    return [e["kind"] for e in state.get("album") or []]


def test_album_entry_carries_rarity_and_place():
    st = {**runtime.default_state(), "location_id": "l1"}
    e = runtime.album_add(TWO_PIECE, st, "golden", "金色", "text")
    assert e["rarity"] == 3 and e["bg"] == "l1"
    assert runtime.album_add(TWO_PIECE, st, "promise", "约", "t")["rarity"] == 1
    assert runtime.album_add(TWO_PIECE, st, "unknown_kind", "x", "t")["rarity"] == 1
    # explicit rarity wins but stays clamped to 1..3
    assert runtime.album_add(TWO_PIECE, st, "date", "d", "t", rarity=9)["rarity"] == 3


def test_assembling_a_layered_secret_is_a_keepsake():
    st = {**runtime.default_state(), "location_id": "l1"}
    o1 = _play(TWO_PIECE, st, "问问 账本")
    assert "f1" in o1["state"]["unlocked_fragment_ids"]
    assert "secret" not in _kinds(o1["state"])          # one piece is not "assembled"
    o2 = _play(TWO_PIECE, o1["state"], "再追 账本")
    assert "f2" in o2["state"]["unlocked_fragment_ids"]
    entries = [e for e in o2["state"]["album"] if e["kind"] == "secret"]
    assert len(entries) == 1
    assert entries[0]["title"] == "账本" and entries[0]["rarity"] == 2
    assert entries[0]["bg"] == "l1" and entries[0]["name"] == "Mara"
    # the celebration rode the moments channel
    assert any(m.get("kind") == "secret_full" for m in o2.get("moments") or [])
    # already assembled → a later turn never re-shelves it
    o3 = _play(TWO_PIECE, o2["state"], "还有呢 账本")
    assert len([e for e in o3["state"]["album"] if e["kind"] == "secret"]) == 1


def test_single_fragment_secret_never_counts_as_assembled():
    st = {**runtime.default_state(), "location_id": "l1"}
    o = _play(ONE_PIECE, st, "问问 账本")
    assert "f1" in o["state"]["unlocked_fragment_ids"]
    assert "secret" not in _kinds(o["state"])


def test_natural_twenty_is_a_keepsake(monkeypatch):
    monkeypatch.setattr(runtime._rng, "randint", lambda a, b: 20)
    st = {**runtime.default_state(), "location_id": "l1"}
    o = _play(TWO_PIECE, st, "我挥拳偷袭那个黑影", channel="do")
    entries = [e for e in o["state"]["album"] if e["kind"] == "crit"]
    assert len(entries) == 1 and entries[0]["rarity"] == 2
    assert any(m.get("kind") == "crit" for m in o.get("moments") or [])


def test_major_breakthrough_is_a_keepsake(monkeypatch):
    monkeypatch.setattr(runtime.random, "randint", lambda a, b: 19)  # 天劫过、顿悟
    monkeypatch.setattr(runtime._rng, "randint", lambda a, b: 10)    # 骰面平平, 不涉奇遇
    st = {**runtime.default_state(), "location_id": "l1"}
    st["cult"] = {"rank": 0, "stage": 3, "prog": 100, "streak": 0, "apt": "中平之资"}
    o = _play(CULT, st, "我要渡劫突破", channel="do")
    entries = [e for e in o["state"]["album"] if e["kind"] == "breakthrough"]
    assert len(entries) == 1 and entries[0]["rarity"] == 3
    assert "斗者" in entries[0]["title"]
    assert any(m.get("kind") == "breakthrough" for m in o.get("moments") or [])
