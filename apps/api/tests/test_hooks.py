"""Daily-return hooks: 悬念离场 (parting cliffhanger beat via /runs/{id}/leave) and
回归问候 (returning flag reaches the primary speaker's prompt)."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.engine import runtime  # noqa: E402
from app.main import app  # noqa: E402

STORY = {
    "story": {"id": "s", "characters": [{"id": "c1", "name": "M", "is_lead": True}],
              "acts": [{"index": 1, "title": "a",
                        "advance": {"required_fragment_ids": ["f1"]}},
                       {"index": 2, "title": "b"}]},
    "secrets": [{"id": "s1", "character_id": "c1", "title": "那本账",
                 "fragments": [{"id": "f1", "content": "BODY", "retrieval_key": "k",
                                "known_by_character_ids": ["c1"],
                                "unlock": {"affinity_min": 999}}]}],
}


def test_parting_hook_is_spoiler_safe_cliffhanger_plus_teaser():
    st = runtime.default_state()
    beats = runtime.build_parting_hook(STORY, st, {"name": "我"})  # MockLLM path
    # one cliffhanger + the 下幕预告 (next act's TITLE only — never its events)
    assert len(beats) == 2 and all(b["type"] == "description" for b in beats)
    assert "BODY" not in beats[0]["text"]          # label only, never the locked content
    assert "那本账" in beats[0]["text"]             # points at the pending topic
    assert "下幕预告" in beats[1]["text"] and "b" in beats[1]["text"]
    assert "BODY" not in beats[1]["text"]


def test_returning_flag_reaches_primary_prompt():
    seen = {}

    class SpyLLM:
        def generate(self, prompt):
            if prompt.get("speaker_name"):
                seen["returning"] = prompt.get("returning")
            return {"beats": [{"type": "dialogue", "speaker_name": prompt.get("speaker_name"),
                               "text": "回来啦"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}

    st = runtime.default_state()
    got_beat = False
    for kind, payload in runtime.run_turn_stream(STORY, st, {"name": "我"}, "我回来了",
                                                 channel="say", llm=SpyLLM(), returning=True):
        if kind == "beat":
            got_beat = True
    assert seen.get("returning") is True
    assert got_beat


def test_leave_endpoint_appends_hook_once():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        c.post("/api/v1/auth/signup",
               json={"email": "hook@x.com", "password": "password1",
                     "dob": "1990-01-01", "accepted_tos": True})
        sid = c.post("/api/v1/stories",
                     json={"title": "钩子测试", "visibility": "public",
                           "characters": [{"id": "c1", "name": "M", "is_lead": True}],
                           "acts": [{"index": 1, "title": "开场"}]}).json()["id"]
        c.post(f"/api/v1/stories/{sid}/publish")
        persona = c.post("/api/v1/personas", json={"name": "我"}).json()
        rid = c.post("/api/v1/runs",
                     json={"story_id": sid, "persona_id": persona["id"]}).json()["id"]

        n0 = len(c.get(f"/api/v1/runs/{rid}/play").json())
        # leaving BEFORE any conversation adds nothing (no thread to hang a hook on)
        assert c.post(f"/api/v1/runs/{rid}/leave").status_code == 204
        assert len(c.get(f"/api/v1/runs/{rid}/play").json()) == n0

        c.post(f"/api/v1/runs/{rid}/play", json={"input": "你好", "channel": "say"})
        n1 = len(c.get(f"/api/v1/runs/{rid}/play").json())
        assert c.post(f"/api/v1/runs/{rid}/leave").status_code == 204
        n2 = len(c.get(f"/api/v1/runs/{rid}/play").json())
        assert n2 == n1 + 1                     # exactly one cliffhanger beat appended
        assert c.post(f"/api/v1/runs/{rid}/leave").status_code == 204
        assert len(c.get(f"/api/v1/runs/{rid}/play").json()) == n2  # idempotent per leave point
