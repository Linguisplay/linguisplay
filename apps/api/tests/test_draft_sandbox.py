# -*- coding: utf-8 -*-
"""🏜 问卷→沙盒本 e2e (MockLLM): 答案进, 私有可玩的沙盒本出。
断言全链: 九键形状 / 单幕无结局 / lint 干净 / 玩家真的能开局 / 配额闸。"""
import os
import time
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_draft_sandbox.db")
os.environ.setdefault("JWT_SECRET", "test")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.engine import logic as logic_mod  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Story  # noqa: E402

ANSWERS = {"题材": "修仙", "世界观": "灵脉将枯的山城", "超凡体系": "剑心",
           "金手指": "能看见他人头顶的死期", "分级": "全年龄"}
SUMMARY = "云脊山脉深处的问剑小城，宗门林立而灵脉将枯。" * 3


@pytest.fixture()
def c():
    init_db()
    cl = TestClient(app)
    r = cl.post("/api/v1/auth/signup", json={
        "email": f"sb-{uuid.uuid4().hex[:8]}@survey.com",
        "password": "pw12345678", "dob": "1990-01-01", "accepted_tos": True})
    assert r.status_code in (200, 201), r.text
    yield cl


def _build(cl):
    r = cl.post("/api/v1/stories/draft_sandbox",
                json={"answers": ANSWERS, "summary": SUMMARY, "title": "我的小世界"})
    assert r.status_code == 200, r.text
    jid = r.json()["job"]
    for _ in range(40):   # Mock 秒级完成, 上限 8s 防呆
        st = cl.get(f"/api/v1/stories/draft_sandbox/{jid}").json()
        if st["status"] != "working":
            return st
        time.sleep(0.2)
    raise AssertionError("job 没完成")


def test_summary_endpoint_writes_a_summary(c):
    r = c.post("/api/v1/stories/draft_sandbox/summary", json={"answers": ANSWERS})
    assert r.status_code == 200, r.text
    assert len(r.json()["summary"]) >= 30


def test_survey_builds_a_playable_private_sandbox(c):
    st = _build(c)
    assert st["status"] == "done", st.get("error")
    sid = st["story_id"]
    db = SessionLocal()
    row = db.get(Story, sid)
    try:
        assert row.visibility == "private" and row.title == "我的小世界"
        sb = row.sandbox
        assert sb["enabled"] and sb["currency"] == "灵石" and sb["start_money"] == 20
        assert sb["progression"]["name"] == "剑心" and len(sb["progression"]["ranks"]) == 6
        assert sb["opening_visitor"] == "ch_1" and sb["start_location"] == "loc_1"
        assert sb["default_powers"] == ["能看见他人头顶的死期"]
        assert row.endings == [] and len(row.acts) == 1
        assert row.phone == {"enabled": False}      # mock 世界是 ancient
        assert "忌" in (row.style or "")
        assert (row.tuning or {}).get("_origin") == "survey_sandbox"
        content = {"story": {"title": row.title, "characters": row.characters,
                             "acts": row.acts, "locations": row.locations,
                             "endings": row.endings, "sandbox": row.sandbox},
                   "secrets": []}
        errs = [i for i in logic_mod.lint_story(content) if i.get("severity") == "error"]
        assert not errs, f"起草物过不了发布硬门: {errs}"
    finally:
        db.close()
    # 答完即玩: owner 对自己的私有草稿直接开局 (runs.py:593 放行)
    pid = c.post("/api/v1/personas", json={"name": "铸世者"}).json()["id"]
    rr = c.post("/api/v1/runs", json={"story_id": sid, "persona_id": pid})
    assert rr.status_code == 201, rr.text


def test_thin_summary_is_refused(c):
    r = c.post("/api/v1/stories/draft_sandbox",
               json={"answers": ANSWERS, "summary": "太薄"})
    assert r.status_code == 400


def test_daily_quota_is_three(c):
    for _ in range(3):
        st = _build(c)
        assert st["status"] == "done"
    r = c.post("/api/v1/stories/draft_sandbox",
               json={"answers": ANSWERS, "summary": SUMMARY})
    assert r.status_code == 429, "第 4 次要被拦 — 每日 3 次"


def test_summary_quota_429(c):
    from app.routers import stories as stories_mod
    import time as _t
    # 直接把当日计数打满 — 别真调 10 次浪费秒数
    uidkey = None
    r = c.post("/api/v1/stories/draft_sandbox/summary", json={"answers": ANSWERS})
    assert r.status_code == 200
    for k in list(stories_mod._SANDBOX_SUM_QUOTA):
        stories_mod._SANDBOX_SUM_QUOTA[k] = 10
        uidkey = k
    assert uidkey
    r = c.post("/api/v1/stories/draft_sandbox/summary", json={"answers": ANSWERS})
    assert r.status_code == 429


def test_quota_day_frame_is_utc():
    """配额日界必须与 created_at 同帧 (UTC) — 本地墙钟版在上海时区每天有 8 小时漏计窗。"""
    from datetime import datetime, timezone
    from app.routers import stories as stories_mod
    assert stories_mod._utc_today() == datetime.now(timezone.utc).strftime("%Y%m%d")
    d0 = stories_mod._utc_day_start()
    assert d0.hour == 0 and d0.date() == datetime.now(timezone.utc).date()
