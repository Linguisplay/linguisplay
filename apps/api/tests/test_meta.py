"""🌱 Achievements & NG+ (二周目): endings outlive the run in a per-(user,story) meta —
a cross-run gallery, story-agnostic achievements, and start perks earned by finishing
once. Engine layer pure; HTTP layer proves the bump + the perk gate."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.engine import runtime  # noqa: E402
from app.main import app  # noqa: E402


def test_compute_achievements_pure():
    content = {"story": {"id": "s", "characters": [{"id": "a", "name": "甲"}],
                         "acts": [{"index": 1, "title": "一"}],
                         "endings": [{"id": "e_true", "kind": "true", "title": "真"}]},
               "secrets": [{"id": "s1", "character_id": "a",
                            "fragments": [{"id": "f1", "content": "x", "retrieval_key": "x",
                                           "unlock": {}}]}]}
    st = runtime.default_state()
    assert runtime.compute_achievements(content, st) == []       # no ending → nothing
    st["achieved_endings"] = ["e_true"]
    st["unlocked_fragment_ids"] = ["f1"]
    st["confronts_won"] = 3
    st["rel"] = {"a": {"closeness": 80, "romance": 90}}
    ids = {a["id"] for a in runtime.compute_achievements(content, st)}
    assert ids == {"true_end", "no_blood", "all_truths", "heartbeat", "interrogator", "swift"}
    # deaths void the pacifist badge; a long run voids 雷厉风行
    st["dead_character_ids"] = ["a"]
    st["clock"] = {"day": 4, "slot": 0, "turns_in_slot": 0}
    ids2 = {a["id"] for a in runtime.compute_achievements(content, st)}
    assert "no_blood" not in ids2 and "swift" not in ids2


def test_meta_accumulates_and_gates_ng_plus():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        c.post("/api/v1/auth/signup",
               json={"email": "m@x.com", "password": "password1",
                     "dob": "1990-01-01", "accepted_tos": True})
        story = c.post("/api/v1/stories", json={
            "title": "Meta", "visibility": "public",
            "characters": [{"id": "c1", "name": "阿元", "is_lead": True}],
            "acts": [{"index": 1, "title": "一"}],
            "endings": [{"id": "e1", "kind": "normal", "title": "落幕"}],
        }).json()
        sid = story["id"]
        c.post(f"/api/v1/stories/{sid}/publish")
        persona = c.post("/api/v1/personas", json={"name": "Ash", "pronouns": "they"}).json()

        # NG+ perks are LOCKED before any ending has been reached
        r = c.post("/api/v1/runs", json={"story_id": sid, "persona_id": persona["id"],
                                         "perk": "veteran"})
        assert r.status_code == 403
        # fresh meta reads empty and locked
        m0 = c.get(f"/api/v1/stories/{sid}/meta").json()
        assert m0["endings_achieved"] == [] and m0["ng_plus"] is False
        assert m0["endings_total"] == 1 and {p["id"] for p in m0["perks"]} == {"veteran", "instinct"}

        # a run reaches the (condition-free, final-act) ending on its first turn
        run = c.post("/api/v1/runs", json={"story_id": sid, "persona_id": persona["id"]}).json()
        t = c.post(f"/api/v1/runs/{run['id']}/play", json={"input": "你好", "channel": "say"}).text
        assert '"ending"' in t and '"achievements"' in t and "一滴血都没流" in t

        m1 = c.get(f"/api/v1/stories/{sid}/meta").json()
        assert m1["endings_achieved"] == ["e1"] and m1["ng_plus"] is True
        assert m1["runs_ended"] == 1
        ach = {a["id"] for a in m1["achievements"]}
        assert "no_blood" in ach and "swift" in ach and "true_end" not in ach

        # NG+ now unlocked: 故人 starts every relationship warmer…
        run2 = c.post("/api/v1/runs", json={"story_id": sid, "persona_id": persona["id"],
                                            "perk": "veteran"}).json()
        prof = c.get(f"/api/v1/runs/{run2['id']}/character/c1").json()
        assert prof["closeness"] == 5 + runtime.VETERAN_CLOSENESS
        # …直觉 is accepted too; nonsense perks are refused
        assert c.post("/api/v1/runs", json={"story_id": sid, "persona_id": persona["id"],
                                            "perk": "instinct"}).status_code == 201
        assert c.post("/api/v1/runs", json={"story_id": sid, "persona_id": persona["id"],
                                            "perk": "cheat"}).status_code == 400
