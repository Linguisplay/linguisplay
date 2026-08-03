# -*- coding: utf-8 -*-
"""🕸 关系网视图 (Yi 2026-07-18): 节点=已认识, 边=npc_rel 立场带演变日志。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


def test_relweb_nodes_edges_and_evolution_log():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        c.post("/api/v1/auth/signup",
               json={"email": "web@x.com", "password": "password1",
                     "dob": "1990-01-01", "accepted_tos": True})
        sid = c.post("/api/v1/stories", json={
            "title": "网", "visibility": "public",
            "characters": [
                {"id": "a", "name": "甲", "is_lead": True,
                 "ties": [{"char_id": "b", "stance": -2, "label": "为一桩旧账反目"}]},
                {"id": "b", "name": "乙"}, {"id": "c", "name": "丙"}],
            "acts": [{"index": 1, "title": "一"}]}).json()["id"]
        c.post(f"/api/v1/stories/{sid}/publish")
        pid = c.post("/api/v1/personas", json={"name": "我"}).json()["id"]
        rid = c.post("/api/v1/runs", json={"story_id": sid, "persona_id": pid}).json()["id"]
        c.post(f"/api/v1/runs/{rid}/play", json={"input": "你们好", "channel": "say"})
        # 直接演化一步 (引擎 API): 甲乙立场 -2 → -1, 日志入账
        from app.db import SessionLocal
        from app.engine import runtime
        db = SessionLocal()
        try:
            from app.models import Run as RunModel
            r = db.get(RunModel, rid)
            st = dict(r.state or {})
            st["met_ids"] = ["a", "b", "c"]
            runtime._ensure_npc_rel(r.pinned_content or {}, st)
            # 拆向后边是 {ab, ba, log} (0e14595): 方向视图各归各, 读一律走 npc_stance
            assert runtime.npc_stance(st, "a", "b")["stance"] == -2   # 授权 ties 播了种
            st["npc_rel"]["a|b"]["ab"]["stance"] = -1
            st["npc_rel"]["a|b"]["ba"]["stance"] = -1
            st["npc_rel"]["a|b"]["log"] = [{"act": 1, "delta": 1, "why": "乙替甲挡了一刀"}]
            r.state = st
            from sqlalchemy.orm.attributes import flag_modified
            flag_modified(r, "state")
            db.commit()
        finally:
            db.close()
        web = c.get(f"/api/v1/runs/{rid}/relweb").json()
        assert {n["id"] for n in web["nodes"]} == {"a", "b", "c"}
        e = next(x for x in web["edges"] if {x["a"], x["b"]} == {"a", "b"})
        assert e["stance"] == -1
        assert e["log"][0]["why"] == "乙替甲挡了一刀"       # 随时间变化, 有账可查
        assert not any({x["a"], x["b"]} == {"a", "c"} for x in web["edges"])  # 无立场不画线
