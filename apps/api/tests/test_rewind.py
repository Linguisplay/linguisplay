"""重说/回溯 (docs/ux-design.md P1): every player turn is a rewind point — the run's
pre-turn state rides on the player beat, POST /runs/{id}/rewind restores it and drops
everything from that turn on. A bad beat's exit is a button, not a bug report."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


def _boot(c):
    c.post("/api/v1/auth/signup",
           json={"email": "rewind@x.com", "password": "password1",
                 "dob": "1990-01-01", "accepted_tos": True})
    story = c.post("/api/v1/stories", json={
        "title": "Rewind", "visibility": "public",
        "characters": [{"id": "c1", "name": "阿元", "is_lead": True}],
        "acts": [{"index": 1, "title": "一"}],
    }).json()
    c.post(f"/api/v1/stories/{story['id']}/publish")
    persona = c.post("/api/v1/personas", json={"name": "Ash", "pronouns": "they"}).json()
    run = c.post("/api/v1/runs", json={"story_id": story["id"],
                                       "persona_id": persona["id"]}).json()
    return run["id"]


def test_rewind_restores_state_and_truncates_beats():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        rid = _boot(c)
        n0 = len(c.get(f"/api/v1/runs/{rid}/play").json())
        c.post(f"/api/v1/runs/{rid}/play", json={"input": "你好", "channel": "say"})
        c.post(f"/api/v1/runs/{rid}/play", json={"input": "再聊聊", "channel": "say"})
        beats = c.get(f"/api/v1/runs/{rid}/play").json()
        assert len(beats) > n0 + 2
        second_player_seq = [b["seq"] for b in beats if b["author"] == "player"][1]

        # ↻ 重说 (no seq): drops the LAST player turn and everything after it
        r = c.post(f"/api/v1/runs/{rid}/rewind", json={})
        assert r.status_code == 200
        after = c.get(f"/api/v1/runs/{rid}/play").json()
        assert all(b["seq"] < second_player_seq for b in after)
        assert sum(1 for b in after if b["author"] == "player") == 1

        # ⏪ 回溯 (explicit seq): back to before the FIRST player turn — opening only
        first_player_seq = [b["seq"] for b in after if b["author"] == "player"][0]
        assert c.post(f"/api/v1/runs/{rid}/rewind",
                      json={"seq": first_player_seq}).status_code == 200
        opening = c.get(f"/api/v1/runs/{rid}/play").json()
        assert len(opening) == n0
        assert not any(b["author"] == "player" for b in opening)

        # nothing left to rewind → a clear 400, not a crash
        assert c.post(f"/api/v1/runs/{rid}/rewind", json={}).status_code == 400

        # …and the run still plays normally after rewinding
        r = c.post(f"/api/v1/runs/{rid}/play", json={"input": "重新来过", "channel": "say"})
        assert r.status_code == 200


def test_rewind_takes_the_erased_timelines_creations_with_it():
    """Yi 2026-07-09: 重说要清记忆 — a character minted by the erased timeline must
    vanish with it (content_before snapshot rides the mutating turn's first beat)."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        rid = _boot(c)
        c.post(f"/api/v1/runs/{rid}/play", json={"input": "你好", "channel": "say"})
        c.post(f"/api/v1/runs/{rid}/play", json={"input": "去打听", "channel": "say"})
        beats = c.get(f"/api/v1/runs/{rid}/play").json()
        p2 = [b for b in beats if b["author"] == "player"][1]["seq"]

        # simulate what a minting turn does: pre-turn content pinned to the turn's
        # first beat, then the run's story copy grows a character
        from app.db import SessionLocal
        from app.models import Beat as BeatModel, Run as RunModel
        import copy, json
        db = SessionLocal()
        r = db.get(RunModel, rid)
        pristine = copy.deepcopy(r.pinned_content)
        fb = (db.query(BeatModel).filter(BeatModel.run_id == rid, BeatModel.seq == p2)
              .first())
        fb.content_before = pristine
        pc = json.loads(json.dumps(r.pinned_content))
        pc["story"]["characters"].append({"id": "gen_x", "name": "时间线私生子",
                                          "generated": True})
        r.pinned_content = pc
        db.commit()
        db.close()

        assert c.post(f"/api/v1/runs/{rid}/rewind", json={"seq": p2}).status_code == 200
        run = c.get(f"/api/v1/runs/{rid}").json()
        db = SessionLocal()
        names = [ch.get("name") for ch in
                 (db.get(RunModel, rid).pinned_content.get("story") or {})
                 .get("characters", [])]
        db.close()
        assert "时间线私生子" not in names   # erased with the timeline that made it
        assert run["id"] == rid
