# -*- coding: utf-8 -*-
"""🙈 整理书架 (Yi 2026-08-03:「把之前做的不好的剧本和沙盒都隐藏一下, 只留下好的」)。

隐藏 = 设私密。它必须是【可逆且不伤人】的一刀:
  ① 藏起来的本子从玩家大厅消失
  ② 但工坊照旧列得出来、照旧能开 (否则作者藏完就再也找不回来了)
  ③ 老存档照旧能续 (已经在玩的人不该被一个整理动作踢下线)
  ④ 只动 visibility 一个字段 — 不碰内容、不碰版本、不碰发布状态
"""
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_shelf.db")
os.environ.setdefault("JWT_SECRET", "test")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Story  # noqa: E402

FULL = {
    "visibility": "public", "synopsis": "一句梗概",
    "acts": [{"index": 1, "title": "一幕"}],
    "characters": [{"id": "c1", "name": "甲角", "is_lead": True, "playable": True}],
    "locations": [{"id": "l1", "name": "门厅", "detail": "x", "exits": []}],
    "endings": [{"id": "e1", "kind": "true", "title": "真结局", "text": "答案"}],
}


@pytest.fixture()
def author():
    init_db()
    c = TestClient(app)
    r = c.post("/api/v1/auth/signup", json={
        "email": f"shelf-{uuid.uuid4().hex[:8]}@sharedlib.com",
        "password": "pw12345678", "dob": "1990-01-01", "accepted_tos": True})
    assert r.status_code in (200, 201), r.text
    sid = c.post("/api/v1/stories", json={"title": "要被藏的本子"}).json()["id"]
    c.patch(f"/api/v1/stories/{sid}", json=FULL)
    assert c.post(f"/api/v1/stories/{sid}/publish").status_code == 200
    yield c, sid
    db = SessionLocal()
    s = db.get(Story, sid)
    if s:
        db.delete(s)
        db.commit()
    db.close()


def _hide(c, sid, vis="private"):
    r = c.post("/api/v1/me/stories/visibility",
               json={"ids": [sid], "visibility": vis})
    assert r.status_code == 200, r.text
    return r.json()


def test_hiding_takes_it_out_of_the_player_lobby(author):
    c, sid = author
    assert any(x["id"] == sid for x in c.get("/api/v1/stories").json()["items"])
    assert _hide(c, sid)["changed"] == 1
    assert not any(x["id"] == sid for x in c.get("/api/v1/stories").json()["items"])


def test_a_hidden_story_is_still_in_the_studio_and_still_opens(author):
    """藏完就找不回来 = 数据丢失级的坑。工坊必须照旧列得出、开得了。"""
    c, sid = author
    _hide(c, sid)
    row = next((x for x in c.get("/api/v1/me/stories").json() if x["id"] == sid), None)
    assert row, "藏起来的本子从工坊列表里消失了 — 作者再也找不回来"
    assert row["visibility"] == "private"
    assert c.get(f"/api/v1/stories/{sid}?edit=1").status_code == 200


def test_an_existing_save_keeps_working_after_its_story_is_hidden(author):
    """整理书架不该把正在玩的人踢下线。"""
    c, sid = author
    pid = c.post("/api/v1/personas", json={"name": "玩家人格"}).json()["id"]
    rid = c.post("/api/v1/runs", json={"story_id": sid, "persona_id": pid}).json()["id"]
    _hide(c, sid)
    assert c.get(f"/api/v1/runs/{rid}").status_code == 200, "藏一下就把活档续不了了"


def test_it_only_touches_visibility(author):
    c, sid = author
    before = c.get(f"/api/v1/stories/{sid}?edit=1").json()
    _hide(c, sid)
    after = c.get(f"/api/v1/stories/{sid}?edit=1").json()
    assert after["status"] == before["status"] and after["version"] == before["version"]
    for k in ("title", "characters", "acts", "locations", "endings"):
        assert after[k] == before[k], f"整理书架动了 {k} — 它只该翻可见性"


def test_hiding_is_reversible(author):
    c, sid = author
    _hide(c, sid)
    assert _hide(c, sid, "public")["changed"] == 1
    assert any(x["id"] == sid for x in c.get("/api/v1/stories").json()["items"])


def test_already_at_that_visibility_counts_as_no_change(author):
    c, sid = author
    _hide(c, sid)
    assert _hide(c, sid)["changed"] == 0, "重复隐藏不该报改了 N 本"


def test_a_bogus_visibility_is_refused(author):
    c, sid = author
    r = c.post("/api/v1/me/stories/visibility",
               json={"ids": [sid], "visibility": "hidden"})
    assert r.status_code == 400, "只认 private / public — 别把一个乱值写进库"


def test_the_studio_list_carries_the_evidence_the_author_ticks_on(author):
    """勾选界面靠这几个数摆证据。少一个字段, 作者就是在盲勾。"""
    c, sid = author
    row = next(x for x in c.get("/api/v1/me/stories").json() if x["id"] == sid)
    for k in ("chars", "locs", "sprites", "bgs", "runs", "sandbox"):
        assert k in row, f"工坊列表少了 {k} — 整理书架时看不见这本好不好"
    assert row["chars"] == 1 and row["locs"] == 1
    assert row["sprites"] == 0 and row["bgs"] == 0   # 这本没排过图
    assert row["runs"] == 0 and row["sandbox"] is False
