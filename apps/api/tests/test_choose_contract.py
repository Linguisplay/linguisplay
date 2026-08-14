# -*- coding: utf-8 -*-
"""📜 /choose 的返回形状进契约 (交接审计 2026-08-14: 金路径 8 个接口里唯独它的
2xx schema 是字面量 {} — 前端 codegen 出来是 any, 只能打一次接口去摸)。

两个用例分工:
  ① 契约里必须声明 label/flag/killed/moved_to 四个键 (今天红, 补上 response_model 转绿)
  ② 钉住线上真实响应不许变 (今天就绿, 防的是加模型时改名/丢键 — response_model
     会静默滤掉模型里没有的键, 这一钉就是为它准备的)
"""
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_choose_contract.db")
os.environ.setdefault("JWT_SECRET", "test")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Run  # noqa: E402

STORY = {
    "visibility": "public", "synopsis": "一句梗概",
    "acts": [{"index": 1, "title": "一幕",
              "choice": {"prompt": "现在去哪",
                         "options": [{"id": "optA", "label": "去天台",
                                      "flag": "went_roof"}]}}],
    "characters": [{"id": "c1", "name": "甲角", "is_lead": True, "playable": True}],
    "locations": [{"id": "loc_choose_probe", "name": "教室", "detail": "x", "exits": []}],
    "endings": [{"id": "e1", "kind": "true", "title": "真结局", "text": "答案"}],
}


def _resolve(spec: dict, schema: dict) -> dict:
    while "$ref" in (schema or {}):
        name = schema["$ref"].rsplit("/", 1)[-1]
        schema = spec["components"]["schemas"][name]
    return schema or {}


def test_the_contract_declares_what_choose_returns():
    spec = app.openapi()
    op = spec["paths"]["/api/v1/runs/{run_id}/choose"]["post"]
    schema = _resolve(spec, op["responses"]["200"]["content"]["application/json"]["schema"])
    props = schema.get("properties") or {}
    for k in ("label", "flag", "killed", "moved_to"):
        assert k in props, (
            f"/choose 的契约缺 {k} — codegen 出来是 any, 前端只能打一次接口去摸")


@pytest.fixture()
def pending_run():
    init_db()
    c = TestClient(app)
    r = c.post("/api/v1/auth/signup", json={
        "email": f"choose-{uuid.uuid4().hex[:8]}@contract.com",
        "password": "pw12345678", "dob": "1990-01-01", "accepted_tos": True})
    assert r.status_code in (200, 201), r.text
    sid = c.post("/api/v1/stories", json={"title": "抉择契约本"}).json()["id"]
    c.patch(f"/api/v1/stories/{sid}", json=STORY)
    assert c.post(f"/api/v1/stories/{sid}/publish").status_code == 200
    pid = c.post("/api/v1/personas", json={"name": "契约玩家"}).json()["id"]
    rid = c.post("/api/v1/runs", json={"story_id": sid, "persona_id": pid}).json()["id"]
    db = SessionLocal()
    run = db.get(Run, rid)
    st = dict(run.state or {})
    st["pending_choice"] = {"act": 1, "key": "act1"}
    run.state = st
    db.commit()
    db.close()
    yield c, rid
    # 🧹 开局会给 loc_choose_probe 异步排一张关键词兜底图 — 别让测试往工作区拉屎
    # (shelf 测试同款教训: /scene/bg 是按地点 id stat 文件的)
    import pathlib
    bg = (pathlib.Path(__file__).resolve().parents[1]
          / "app" / "static" / "scene" / "bg" / "loc_choose_probe.jpg")
    bg.unlink(missing_ok=True)


def test_the_live_response_shape_is_pinned(pending_run):
    c, rid = pending_run
    r = c.post(f"/api/v1/runs/{rid}/choose", json={"option_id": "optA"})
    assert r.status_code == 200, r.text
    assert r.json() == {"label": "去天台", "flag": "went_roof",
                        "killed": None, "moved_to": None}
