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

        # 好感是事件记账制 (Yi 2026-07-25: 不许每句话打分), 「交心」带 8 回合冷却 ——
        # affinity_min=6 要等第二次入账才够。实测: 第 1 拍好感 0→4, 第 2~8 拍冻在 4,
        # 第 9 拍 4→8, 第 10 拍门开。所以这里打到开门为止, 而不是钉死第 3 拍
        # (钉死的写法在事件记账制上线那天就假红了, 却被当成环境噪声挂了一周)。
        probes = ["tell me about the ledger",
                  "come on, the ledger numbers, please",
                  "the ledger, i need to know"]
        opened_at = 0
        for turn in range(1, 13):
            body = play(probes[(turn - 1) % len(probes)])
            state = c.get(f"/api/v1/runs/{rid}").json()["state"]
            if state["unlocked_fragment_ids"]:
                assert SECRET_BODY in body, "解锁的那一拍就该让角色说出来"
                opened_at = turn
                break
            # 门没开的每一拍都必须滴水不漏
            assert SECRET_BODY not in body, f"第 {turn} 拍门还锁着, 正文不许出现秘密正身"

        assert opened_at, "12 拍之内该开的门没开 — 门控或好感经济回归了"
        state = c.get(f"/api/v1/runs/{rid}").json()["state"]
        assert len(state["unlocked_fragment_ids"]) == 1
        assert state["affinity"] >= 6

        # replay returns persisted beats including the player's turns
        beats = c.get(f"/api/v1/runs/{rid}/play").json()
        assert any(b["author"] == "player" for b in beats)
        assert any(SECRET_BODY in b["text"] for b in beats)
