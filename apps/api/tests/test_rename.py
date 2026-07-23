# -*- coding: utf-8 -*-
"""🪪 NPC 改名 (Yi 2026-07: 实弹出过一个叫「谁看见」的涌现NPC): 玩家可给涌现角色
改名（run 私有副本，不碰母本）；作者写定的角色不许改；新名过同一套名字守卫。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm.attributes import flag_modified  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


def test_rename_emergent_character():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        c.post("/api/v1/auth/signup",
               json={"email": "rn@x.com", "password": "password1",
                     "dob": "1990-01-01", "accepted_tos": True})
        sid = c.post("/api/v1/stories", json={
            "title": "改名", "visibility": "public",
            "characters": [{"id": "a", "name": "甲", "is_lead": True}],
            "acts": [{"index": 1, "title": "一"}]}).json()["id"]
        c.post(f"/api/v1/stories/{sid}/publish")
        pid = c.post("/api/v1/personas", json={"name": "我"}).json()["id"]
        rid = c.post("/api/v1/runs", json={"story_id": sid, "persona_id": pid}).json()["id"]

        # a bad birth slipped in (pre-guard save): inject an emergent char named「谁看见」
        from app.db import SessionLocal
        from app.models import Run as RunModel
        db = SessionLocal()
        r = db.get(RunModel, rid)
        content = dict(r.pinned_content or {})
        content["story"]["characters"].append(
            {"id": "gen_bad1", "name": "谁看见", "role": "新登场的人物",
             "relation_default": "stranger", "generated": True})
        r.pinned_content = content
        flag_modified(r, "pinned_content")
        st = dict(r.state or {})
        st["promises"] = [{"char_id": "gen_bad1", "char_name": "谁看见",
                           "what": "明早碰头", "day": 2, "slot": "morning", "status": "open"}]
        r.state = st
        flag_modified(r, "state")
        db.commit()
        db.close()

        # ✅ rename the emergent char — profile and promise snapshot both follow
        out = c.post(f"/api/v1/runs/{rid}/character/gen_bad1/rename", json={"name": "老周"})
        assert out.status_code == 200 and out.json()["name"] == "老周" and out.json()["was"] == "谁看见"
        prof = c.get(f"/api/v1/runs/{rid}/character/gen_bad1").json()
        assert prof["name"] == "老周"
        db = SessionLocal()
        r = db.get(RunModel, rid)
        assert r.state["promises"][0]["char_name"] == "老周"
        db.close()

        # 🚫 authored characters keep their author-given names
        assert c.post(f"/api/v1/runs/{rid}/character/a/rename",
                      json={"name": "乙"}).status_code == 403
        # 🚫 the new name passes the same guard births do
        assert c.post(f"/api/v1/runs/{rid}/character/gen_bad1/rename",
                      json={"name": "谁在门外"}).status_code == 400
        # 🚫 no duplicate names
        assert c.post(f"/api/v1/runs/{rid}/character/gen_bad1/rename",
                      json={"name": "甲"}).status_code == 409
        # 🚫 unknown char
        assert c.post(f"/api/v1/runs/{rid}/character/nobody/rename",
                      json={"name": "老赵"}).status_code == 404


def test_rename_emergent_location_cascades_exits():
    """📍 涌现地点改名 (Yi: 生成的名字乱, 首次落成给机会): 授权地点 403;
    改名级联全图出口 (出口按地名字符串连的)。"""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        c.post("/api/v1/auth/signup",
               json={"email": "rl@x.com", "password": "password1",
                     "dob": "1990-01-01", "accepted_tos": True})
        sid = c.post("/api/v1/stories", json={
            "title": "地名", "visibility": "public",
            "characters": [{"id": "a", "name": "甲", "is_lead": True}],
            "acts": [{"index": 1, "title": "一"}],
            "locations": [{"id": "l1", "name": "门厅", "exits": []}]}).json()["id"]
        c.post(f"/api/v1/stories/{sid}/publish")
        pid = c.post("/api/v1/personas", json={"name": "我"}).json()["id"]
        rid = c.post("/api/v1/runs", json={"story_id": sid, "persona_id": pid}).json()["id"]
        from app.db import SessionLocal
        from app.models import Run as RunModel
        db = SessionLocal()
        r = db.get(RunModel, rid)
        content = dict(r.pinned_content or {})
        content["story"]["locations"].append(
            {"id": "loc_gen1", "name": "那个什么高地", "generated": True, "exits": ["门厅"]})
        content["story"]["locations"][0]["exits"] = ["那个什么高地"]
        r.pinned_content = content
        flag_modified(r, "pinned_content")
        db.commit()
        db.close()
        out = c.post(f"/api/v1/runs/{rid}/location/loc_gen1/rename", json={"name": "落霞岗"})
        assert out.status_code == 200 and out.json()["name"] == "落霞岗"
        db = SessionLocal()
        r = db.get(RunModel, rid)
        locs = r.pinned_content["story"]["locations"]
        assert locs[0]["exits"] == ["落霞岗"]          # 级联出口
        db.close()
        assert c.post(f"/api/v1/runs/{rid}/location/l1/rename",
                      json={"name": "别的"}).status_code == 403   # 授权地点不许改
