# -*- coding: utf-8 -*-
"""📚 大厅翻页 (交接审计 2026-08-14: cursor 是收了就扔的死参数, next_cursor 恒 null,
结果硬顶 50 条 — 前端做无限滚动翻不了页)。

合同: cursor 传上一页给的 next_cursor; 页大小 50; 翻完 next_cursor=null;
乱传的 cursor 明着 400, 不许悄悄当第一页。

用 q 检索圈住本测试自己播的种: 全套件共用一个 SQLite 文件, 大厅列的是所有
公开本子, 不圈的话别的测试留下的公开本会混进页里, 断言数目就成了掷骰子。
"""
import os
import uuid
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_stories_paging.db")
os.environ.setdefault("JWT_SECRET", "test")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Story, User  # noqa: E402

SHELF = 55  # 一页半: 第二页正好 5 本


@pytest.fixture()
def shelf():
    """播 55 本公开已发布的本子 (直插库 — 走 55 遍发布流程太慢), 带唯一检索记号。"""
    init_db()
    c = TestClient(app)
    mark = f"paging{uuid.uuid4().hex[:8]}"
    email = f"{mark}@paging.com"
    r = c.post("/api/v1/auth/signup", json={
        "email": email, "password": "pw12345678",
        "dob": "1990-01-01", "accepted_tos": True})
    assert r.status_code in (200, 201), r.text
    db = SessionLocal()
    uid = db.query(User).filter(User.email == email).one().id
    base = datetime(2026, 1, 1)
    ids = []
    for i in range(SHELF):
        s = Story(owner_id=uid, title=f"{mark} 第{i:02d}本",
                  visibility="public", status="published",
                  updated_at=base + timedelta(minutes=i))
        db.add(s)
        ids.append(s)
    db.commit()
    ids = [s.id for s in ids]
    db.close()
    yield c, mark, ids
    db = SessionLocal()
    for sid in ids:
        s = db.get(Story, sid)
        if s:
            db.delete(s)
    db.commit()
    db.close()


def _page(c, mark, cursor=None):
    params = {"q": mark}
    if cursor is not None:
        params["cursor"] = cursor
    r = c.get("/api/v1/stories", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_the_first_page_hands_out_a_cursor_when_more_remain(shelf):
    c, mark, _ = shelf
    body = _page(c, mark)
    assert len(body["items"]) == 50
    assert body["next_cursor"], "还有 5 本没列出来, next_cursor 却是空的 — 翻页断头"


def test_the_second_page_finishes_the_shelf_without_overlap(shelf):
    c, mark, ids = shelf
    p1 = _page(c, mark)
    p2 = _page(c, mark, cursor=p1["next_cursor"])
    got1 = {x["id"] for x in p1["items"]}
    got2 = {x["id"] for x in p2["items"]}
    assert len(p2["items"]) == SHELF - 50
    assert p2["next_cursor"] is None, "书架翻完了还在发 cursor — 前端会永远加载下一页"
    assert not got1 & got2, "两页有重复 — 玩家会看到同一本出现两次"
    assert got1 | got2 == set(ids), "两页拼起来少了本子"


def test_a_cursor_past_the_end_is_an_empty_page_not_an_error(shelf):
    c, mark, _ = shelf
    body = _page(c, mark, cursor="9999")
    assert body["items"] == []
    assert body["next_cursor"] is None


def test_a_bogus_cursor_is_refused_loudly(shelf):
    c, mark, _ = shelf
    r = c.get("/api/v1/stories", params={"q": mark, "cursor": "不是数字"})
    assert r.status_code == 400, (
        "乱传 cursor 应该明着 400 — 悄悄当第一页会让翻页 bug 永远查不出来")
