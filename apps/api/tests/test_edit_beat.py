# -*- coding: utf-8 -*-
"""✏️ 编辑对话正史 (Yi 2026-07-23: 自己的话/角色台词/旁白都能改): 只改文本不重算账本;
引擎侧文本吃标点守卫, 玩家原话不动; 越权/越档/空文/超长全拦。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Beat as BeatModel  # noqa: E402


def test_edit_history_beats():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        c.post("/api/v1/auth/signup",
               json={"email": "eb@x.com", "password": "password1",
                     "dob": "1990-01-01", "accepted_tos": True})
        sid = c.post("/api/v1/stories", json={
            "title": "编辑", "visibility": "public",
            "characters": [{"id": "a", "name": "甲", "is_lead": True}],
            "acts": [{"index": 1, "title": "一"}]}).json()["id"]
        c.post(f"/api/v1/stories/{sid}/publish")
        pid = c.post("/api/v1/personas", json={"name": "我"}).json()["id"]
        rid = c.post("/api/v1/runs", json={"story_id": sid, "persona_id": pid}).json()["id"]

        # 直接种三拍: 玩家的话 / 角色台词 / 旁白
        db = SessionLocal()
        rows = [BeatModel(run_id=rid, seq=1, type="dialogue", speaker_name=None,
                          text="我要走了", author="player"),
                BeatModel(run_id=rid, seq=2, type="dialogue", speaker_name="甲",
                          text="站住。", author="engine"),
                BeatModel(run_id=rid, seq=3, type="description", speaker_name=None,
                          text="风把门吹开了。", author="engine")]
        db.add_all(rows)
        db.commit()
        ids = [r.id for r in rows]
        db.close()

        # ✅ 三种拍都能改; 引擎侧文本吃 dedash, 玩家原话不动
        assert c.patch(f"/api/v1/runs/{rid}/beat/{ids[0]}",
                       json={"text": "我改主意了——留下"}).json()["text"] == "我改主意了——留下"
        out = c.patch(f"/api/v1/runs/{rid}/beat/{ids[1]}",
                      json={"text": "站住——把东西留下。"}).json()
        assert out["text"] == "站住，把东西留下。"          # 台词过标点守卫
        assert c.patch(f"/api/v1/runs/{rid}/beat/{ids[2]}",
                       json={"text": "夜风灌了进来。"}).status_code == 200

        # 🚫 空文/超长/野拍
        assert c.patch(f"/api/v1/runs/{rid}/beat/{ids[0]}",
                       json={"text": "  "}).status_code == 400
        assert c.patch(f"/api/v1/runs/{rid}/beat/{ids[0]}",
                       json={"text": "呀" * 601}).status_code == 400
        assert c.patch(f"/api/v1/runs/{rid}/beat/nope", json={"text": "x"}).status_code == 404

        # 🚫 别人的档摸不到
        c.post("/api/v1/auth/signup",
               json={"email": "eb2@x.com", "password": "password1",
                     "dob": "1990-01-01", "accepted_tos": True})
        assert c.patch(f"/api/v1/runs/{rid}/beat/{ids[0]}",
                       json={"text": "篡改"}).status_code in (403, 404)
