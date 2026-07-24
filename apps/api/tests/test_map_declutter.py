# -*- coding: utf-8 -*-
"""🗺 地图收纳 (Yi 2026-07-24: 地点多了小地图乱): 热度小账本单点侦测落账;
map_view 下发分层字段 (kind/heat/pinned/tucked/dormant — 生成的+至多一访+14天
没去=休眠, 授权地点永不休眠); mark 端点置顶/隐藏 (当前所在藏不掉)。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from app.engine import runtime  # noqa: E402

STORY = {"story": {"id": "s",
                   "characters": [{"id": "a", "name": "甲", "is_lead": True,
                                   "home_location_id": "hub"}],
                   "acts": [{"index": 1, "title": "一"}],
                   "locations": [
                       {"id": "hub", "name": "枢纽", "exits": ["旧巷"], "unlock": {}},
                       {"id": "lane", "name": "旧巷", "exits": ["枢纽"], "unlock": {},
                        "generated": True},
                       {"id": "shrine", "name": "野祠", "exits": [], "unlock": {},
                        "generated": True}]},
         "secrets": []}


def test_visit_ledger_and_dormancy():
    st = {**runtime.default_state(), "location_id": "hub"}
    st["clock"] = {"day": 1}
    runtime.note_visit_tick(st)
    runtime.note_visit_tick(st)                        # 同地重复不重记
    assert st["loc_visits"]["hub"]["n"] == 1
    st["location_id"] = "lane"
    runtime.note_visit_tick(st)
    assert st["loc_visits"]["lane"] == {"n": 1, "day": 1}
    # 20 天后: 旧巷(生成,一访)休眠; 野祠(生成,零访)休眠; 枢纽(授权)永不休眠
    st["clock"] = {"day": 21}
    st["location_id"] = "hub"
    runtime.note_visit_tick(st)
    nodes = {n["id"]: n for n in runtime.map_view(STORY, st)["nodes"]}
    assert nodes["lane"]["dormant"] and nodes["lane"]["kind"] == "gen"
    assert nodes["shrine"]["dormant"]
    assert not nodes["hub"]["dormant"] and nodes["hub"]["kind"] == "auth"
    assert nodes["hub"]["heat"] == 2                   # 回访+1
    # 置顶豁免休眠; 当前所在也豁免
    st["map_pins"] = ["lane"]
    nodes = {n["id"]: n for n in runtime.map_view(STORY, st)["nodes"]}
    assert not nodes["lane"]["dormant"] and nodes["lane"]["pinned"]


def test_mark_endpoint_roundtrip():
    from fastapi.testclient import TestClient

    from app.db import Base, engine
    from app.main import app
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        c.post("/api/v1/auth/signup",
               json={"email": "mp@x.com", "password": "password1",
                     "dob": "1990-01-01", "accepted_tos": True})
        sid = c.post("/api/v1/stories", json={
            "title": "图", "visibility": "public",
            "characters": [{"id": "a", "name": "甲", "is_lead": True,
                            "home_location_id": "hub"}],
            "acts": [{"index": 1, "title": "一"}],
            "locations": [{"id": "hub", "name": "枢纽", "exits": ["旧巷"]},
                          {"id": "lane", "name": "旧巷", "exits": ["枢纽"]}]}).json()["id"]
        c.post(f"/api/v1/stories/{sid}/publish")
        pid = c.post("/api/v1/personas", json={"name": "我"}).json()["id"]
        rid = c.post("/api/v1/runs", json={"story_id": sid, "persona_id": pid}).json()["id"]
        assert c.post(f"/api/v1/runs/{rid}/map/mark",
                      json={"location_id": "lane", "op": "pin"}).json()["pins"] == ["lane"]
        out = c.post(f"/api/v1/runs/{rid}/map/mark",
                     json={"location_id": "lane", "op": "hide"}).json()
        assert out["hidden"] == ["lane"]
        # 🚫 当前所在藏不掉; 野地点/野操作拦下
        assert c.post(f"/api/v1/runs/{rid}/map/mark",
                      json={"location_id": "hub", "op": "hide"}).status_code == 400
        assert c.post(f"/api/v1/runs/{rid}/map/mark",
                      json={"location_id": "nope", "op": "pin"}).status_code == 404
        assert c.post(f"/api/v1/runs/{rid}/map/mark",
                      json={"location_id": "lane", "op": "explode"}).status_code == 400
        # 图上字段随行
        nodes = {n["id"]: n for n in c.get(f"/api/v1/runs/{rid}/map").json()["nodes"]}
        assert nodes["lane"]["tucked"]
