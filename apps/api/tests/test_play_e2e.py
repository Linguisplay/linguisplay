"""End-to-end proof through the HTTP layer: a locked secret's body never appears
in /play output until the player has probed enough AND affinity has risen."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

SECRET_BODY = "SECRET_BODY_40K"


def test_gate_blocks_then_reveals_through_http():
    # Self-clean: rebuild schema so a stale db file can't carry users between runs.
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        c.post(
            "/api/v1/auth/signup",
            json={"email": "p@x.com", "password": "password1", "dob": "1990-01-01", "accepted_tos": True},
        )
        story = c.post(
            "/api/v1/stories",
            json={"title": "Ledger", "visibility": "public", "characters": [{"id": "c1", "name": "Mara", "is_lead": True}]},
        ).json()
        sid = story["id"]
        c.post(
            f"/api/v1/stories/{sid}/secrets",
            json={
                "character_id": "c1",
                "title": "The hidden ledger",
                "fragments": [
                    {
                        "layer": 1,
                        "content": SECRET_BODY,
                        "retrieval_key": "ledger numbers",
                        "known_by_character_ids": ["c1"],
                        "unlock": {"affinity_min": 6, "act_min": 1, "asks_min": 3},
                    }
                ],
            },
        )
        c.post(f"/api/v1/stories/{sid}/publish")
        persona = c.post("/api/v1/personas", json={"name": "Ash", "pronouns": "they"}).json()
        run = c.post("/api/v1/runs", json={"story_id": sid, "persona_id": persona["id"]}).json()
        rid = run["id"]

        def play(text: str) -> str:
            r = c.post(f"/api/v1/runs/{rid}/play", json={"input": text, "channel": "say"})
            assert r.status_code == 200, r.text
            return r.text

        # turns 1 & 2: probing raises asks + affinity, but not enough → no leak
        t1 = play("tell me about the ledger")
        assert SECRET_BODY not in t1
        t2 = play("come on, the ledger numbers, please")
        assert SECRET_BODY not in t2

        # turn 3: asks>=2 and affinity>=3 now met → fragment reveals
        t3 = play("the ledger, i need to know")
        assert SECRET_BODY in t3, "fragment should have unlocked and surfaced"

        # run state reflects the unlock
        state = c.get(f"/api/v1/runs/{rid}").json()["state"]
        assert len(state["unlocked_fragment_ids"]) == 1
        assert state["affinity"] >= 3

        # replay returns persisted beats including the player's turns
        beats = c.get(f"/api/v1/runs/{rid}/play").json()
        assert any(b["author"] == "player" for b in beats)
        assert any(SECRET_BODY in b["text"] for b in beats)
