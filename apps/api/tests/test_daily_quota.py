# -*- coding: utf-8 -*-
"""💸 上线成本防线: 每用户每日回合配额 (Yi 2026-08-18 上线准备期立).

公开注册后, 一个脚本就能无上限烧 LLM 账单 — drive 有 5 秒最小间隔, 但 say/think
没有任何日上限。法条: DAILY_TURN_QUOTA (默认 0=关, 开发不受影响; 上线在 .env 设数),
计数口径 = 北京时间当天、该用户名下【所有局】的玩家拍 (author='player'),
超了 /play 给 429, 北京时间零点翻篇。

⚠️ 时区教训 (#19 沙盒配额 UTC 帧那课): 日帧必须是北京钟, 且测试用手算常量,
不许镜像实现自己再算一遍。
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from datetime import datetime, timezone  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.routers.runs import _quota_day_start  # noqa: E402


def test_quota_day_starts_at_beijing_midnight():
    # 手算常量: UTC 08-18 17:00 = 北京 08-19 01:00 → 北京当天起点 = UTC 08-18 16:00
    s = _quota_day_start(datetime(2026, 8, 18, 17, 0, tzinfo=timezone.utc))
    assert s == datetime(2026, 8, 18, 16, 0, tzinfo=timezone.utc)
    # UTC 08-18 10:00 = 北京 08-18 18:00 → 北京当天起点 = UTC 08-17 16:00
    s = _quota_day_start(datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc))
    assert s == datetime(2026, 8, 17, 16, 0, tzinfo=timezone.utc)


def test_quota_off_by_default():
    # 出厂 0 = 不设限 — 开发/测试生态不许被这道闸误伤
    assert get_settings().daily_turn_quota == 0


def _signup_and_run(c: TestClient, email: str) -> str:
    """注册(会替换 session cookie 成新用户) → 建本 → 发布 → 开局, 返回 run_id."""
    r = c.post("/api/v1/auth/signup",
               json={"email": email, "password": "password1",
                     "dob": "1990-01-01", "accepted_tos": True})
    assert r.status_code == 201, r.text
    story = c.post("/api/v1/stories",
                   json={"title": "Quota", "visibility": "public",
                         "characters": [{"id": "c1", "name": "Mara",
                                         "is_lead": True}]}).json()
    c.post(f"/api/v1/stories/{story['id']}/publish")
    persona = c.post("/api/v1/personas",
                     json={"name": "Ash", "pronouns": "they"}).json()
    run = c.post("/api/v1/runs",
                 json={"story_id": story["id"], "persona_id": persona["id"]}).json()
    return run["id"]


def test_daily_quota_blocks_and_is_per_user(monkeypatch):
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(get_settings(), "daily_turn_quota", 2)
    with TestClient(app) as c:
        rid = _signup_and_run(c, "quota_a@x.com")
        for i in range(2):
            r = c.post(f"/api/v1/runs/{rid}/play",
                       json={"input": f"聊聊天 {i}", "channel": "say"})
            assert r.status_code == 200, r.text
        # 第 3 拍: 额度花完, 门口就该拦住 (不烧 LLM 不落拍)
        r = c.post(f"/api/v1/runs/{rid}/play",
                   json={"input": "再来一拍", "channel": "say"})
        assert r.status_code == 429, r.text
        assert "额度" in str(r.json().get("detail") or "")
        # 配额是【每用户】的 — 换个人开新局不受 A 的花销影响
        rid_b = _signup_and_run(c, "quota_b@x.com")
        r = c.post(f"/api/v1/runs/{rid_b}/play",
                   json={"input": "你好", "channel": "say"})
        assert r.status_code == 200, r.text


def test_quota_counts_across_runs_of_same_user(monkeypatch):
    """同一用户开小号局绕不过去 — 计数挂在 owner 身上, 不挂在局身上."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(get_settings(), "daily_turn_quota", 2)
    with TestClient(app) as c:
        rid1 = _signup_and_run(c, "quota_c@x.com")
        for i in range(2):
            r = c.post(f"/api/v1/runs/{rid1}/play",
                       json={"input": f"聊 {i}", "channel": "say"})
            assert r.status_code == 200, r.text
        # 同一用户在同一本上再开一局 (persona/story 复用走不通就重建一套)
        story = c.post("/api/v1/stories",
                       json={"title": "Quota2", "visibility": "public",
                             "characters": [{"id": "c1", "name": "Nia",
                                             "is_lead": True}]}).json()
        c.post(f"/api/v1/stories/{story['id']}/publish")
        persona = c.post("/api/v1/personas",
                         json={"name": "Kit", "pronouns": "she"}).json()
        run2 = c.post("/api/v1/runs",
                      json={"story_id": story["id"],
                            "persona_id": persona["id"]}).json()
        r = c.post(f"/api/v1/runs/{run2['id']}/play",
                   json={"input": "新局第一拍", "channel": "say"})
        assert r.status_code == 429, r.text
