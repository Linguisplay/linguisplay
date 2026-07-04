"""Sweep-audit regressions: the public story view never leaks the answer key or
spoilers; the dying stay where they fell; death voids promises; a promise lands where
the character will actually be."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.engine import runtime  # noqa: E402
from app.main import app  # noqa: E402


def test_public_story_view_is_spoiler_free():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        c.post("/api/v1/auth/signup",
               json={"email": "a@x.com", "password": "password1",
                     "dob": "1990-01-01", "accepted_tos": True})
        story = c.post("/api/v1/stories", json={
            "title": "Shield", "visibility": "public",
            "characters": [{"id": "c1", "name": "甲", "is_lead": True, "role": "店主",
                            "agenda": "SPOILER_AGENDA", "knowledge": "SPOILER_LORE",
                            "bio_layers": [{"closeness_min": 40, "text": "SPOILER_BIO"}]}],
            "acts": [{"index": 1, "title": "一",
                      "events": [{"id": "e1", "what_happens": "SPOILER_EVENT"}]}],
            "endings": [{"id": "e_t", "kind": "true", "title": "真", "text": "SPOILER_END"}],
            "verdict": {"prompt": "谁？", "fail_ending_id": "e_t",
                        "options": [{"id": "v1", "label": "甲", "correct": True}]},
        }).json()
        sid = story["id"]
        c.post(f"/api/v1/stories/{sid}/publish")
        # the AUTHOR still sees everything (studio must keep working)
        own = c.get(f"/api/v1/stories/{sid}").json()
        assert own["verdict"] and own["endings"][0]["text"] == "SPOILER_END"
        # a different logged-in player sees the shielded view
        c.post("/api/v1/auth/logout")
        c.post("/api/v1/auth/signup",
               json={"email": "b@x.com", "password": "password1",
                     "dob": "1990-01-01", "accepted_tos": True})
        pub = c.get(f"/api/v1/stories/{sid}").json()
        blob = str(pub)
        assert pub["verdict"] is None and pub["endings"] == []
        for spoiler in ("SPOILER_AGENDA", "SPOILER_LORE", "SPOILER_BIO",
                        "SPOILER_EVENT", "SPOILER_END", "correct"):
            assert spoiler not in blob
        # …but the play UI still gets what it needs
        ch = pub["characters"][0]
        assert ch["name"] == "甲" and ch["role"] == "店主" and "id" in ch


STORY = {
    "story": {"id": "s", "tuning": {"turns_per_slot": 1},
              "characters": [
                  {"id": "a", "name": "甲", "is_lead": True},
                  {"id": "b", "name": "乙",
                   "schedule": [{"from_act": 1, "location_id": "alley", "slots": ["夜"]},
                                {"from_act": 1, "location_id": "hall", "slots": ["晨", "午"]}]},
              ],
              "acts": [{"index": 1, "title": "一"}],
              "locations": [{"id": "hall", "name": "门厅", "detail": "x", "exits": ["后巷"]},
                            {"id": "alley", "name": "后巷", "detail": "y", "exits": ["门厅"]}]},
    "secrets": [],
}


def test_dying_pin_and_promise_hygiene():
    # the dying don't keep their 作息 — they lie where they fell
    st = runtime.default_state()
    st["location_id"] = "hall"
    runtime.set_char_hp(st, "b", "dying")
    runtime._sim(st, "b")["pos"] = "hall"
    st["clock"] = {"day": 1, "slot": 2, "turns_in_slot": 0}   # 夜: schedule says alley
    b = STORY["story"]["characters"][1]
    assert runtime.char_position(STORY, st, b) == "hall"      # pinned, not commuting
    # a promise lands where the character WILL be at that hour (schedule wins over ask)
    tun = runtime.tuning_for(STORY)
    pr = runtime.make_promise(STORY, runtime.default_state(), b,
                              {"what": "夜里见", "day_offset": 1, "slot": "夜", "place": "门厅"},
                              tun)
    assert pr["location_id"] == "alley"                        # his night post, not 门厅
    # death voids open promises — no 爽约 penalty from the grave
    st2 = runtime.default_state()
    st2["promises"] = [{"char_id": "b", "char_name": "乙", "what": "夜里见",
                        "day": 1, "slot": "夜", "location_id": "alley",
                        "romantic": False, "status": "open"}]
    voided = runtime.void_promises_of(st2, "b")
    assert len(voided) == 1 and st2["promises"][0]["status"] == "void"
    assert runtime.promises_view(STORY, st2) == []             # nothing left hanging
