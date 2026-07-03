"""The character dossier (档案卡): the 关系大事记 timeline logs the moments that matter,
and character_profile gathers ONLY what the player may know (bio layers by closeness,
secret titles only once a layer is open, locked content stays server-side)."""

from app.engine import runtime

STORY = {
    "story": {"id": "s", "characters": [
        {"id": "a", "name": "甲", "is_lead": True,
         "bio_layers": [{"closeness_min": 0, "text": "开理发店的。"},
                        {"closeness_min": 30, "text": "BIO_DEEP 他在赎一笔债。"}]},
        {"id": "b", "name": "乙"},
    ], "acts": [{"index": 1, "title": "一"}],
       "locations": [{"id": "hall", "name": "门厅", "detail": "一盏吊灯", "exits": []}]},
    "secrets": [
        {"id": "s1", "character_id": "a", "title": "那笔债",
         "fragments": [{"id": "f1", "content": "SECRET_BODY", "retrieval_key": "债",
                        "unlock": {"asks_min": 1}},
                       {"id": "f2", "content": "SECRET_BODY2", "retrieval_key": "债2",
                        "unlock": {"affinity_min": 999}}]},
        {"id": "s2", "character_id": "a", "title": "另一件事",
         "fragments": [{"id": "f3", "content": "UNTOUCHED", "retrieval_key": "x",
                        "unlock": {"affinity_min": 999}}]},
    ],
}


def test_rel_log_captures_meet_and_reveal():
    st = runtime.default_state()
    out = runtime.run_turn(STORY, st, {"name": "我"}, "跟我说说那笔债", channel="say")
    st = out["state"]
    log_a = st["rel_log"]["a"]
    kinds = [e["kind"] for e in log_a]
    assert "meet" in kinds and "reveal" in kinds          # 初遇 + 吐露真相被记下
    assert any("门厅" in e["text"] for e in log_a if e["kind"] == "meet")
    assert st["met_ids"] == ["a", "b"]
    # second turn doesn't re-log the meeting
    out2 = runtime.run_turn(STORY, st, {"name": "我"}, "你好", channel="say")
    assert [e["kind"] for e in out2["state"]["rel_log"]["a"]].count("meet") == 1


def test_profile_shape_and_no_leaks():
    st = runtime.default_state()
    st = runtime.run_turn(STORY, st, {"name": "我"}, "跟我说说那笔债", channel="say")["state"]
    p = runtime.character_profile(STORY, st, "a")
    blob = str(p)
    assert p["name"] == "甲" and p["is_lead"] and not p["dead"]
    # secret with one open layer shows title + 1/2; untouched secret is a count only
    assert p["secrets"] == [{"title": "那笔债", "unlocked": 1, "total": 2}]
    assert p["secrets_hidden"] == 1
    assert "SECRET_BODY" not in blob and "UNTOUCHED" not in blob and "另一件事" not in blob
    # bio: layer 0 open, deep layer locked behind closeness 30 (start closeness is 5+3)
    assert p["bio"] == ["开理发店的。"] and p["bio_next_at"] == 30
    assert "BIO_DEEP" not in blob
    assert p["where"] is None or isinstance(p["where"], str)
    # closeness high enough → the deep layer unlocks
    st["rel"] = {"a": {"closeness": 40, "romance": 0}}
    p2 = runtime.character_profile(STORY, st, "a")
    assert any("BIO_DEEP" in b for b in p2["bio"]) and p2["bio_next_at"] is None


def test_profile_of_the_dead_and_unknown():
    st = runtime.default_state()
    st["dead_character_ids"] = ["b"]
    p = runtime.character_profile(STORY, st, "b")
    assert p["dead"] is True and p["can_follow"] is False
    assert runtime.character_profile(STORY, st, "nope") is None
