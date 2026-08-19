# -*- coding: utf-8 -*-
"""🔐 撞库/暴破防线 (2026-08-19 上线准备期立).

现网 SSH 一周挨 2.9 万次密码暴破 — 登录 HTTP 口一旦公开只会更多, 而它此前
零防线。法条:
  · 同一邮箱 15 分钟窗口内 5 次密码错误 → 429 锁窗 (对的密码也得等), 成功登录清零
  · 同一 IP 每小时最多 10 次注册 (刷小号绕每日配额的路也顺手堵上)
进程内字典足矣 (单进程部署), 重启清零可接受 — 攻击者拿不到重启按钮。
"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.routers import auth as auth_mod  # noqa: E402


def _fresh():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    auth_mod._LOGIN_FAILS.clear()
    auth_mod._SIGNUP_HITS.clear()


def _signup(c, email):
    return c.post("/api/v1/auth/signup",
                  json={"email": email, "password": "correct-horse1",
                        "dob": "1990-01-01", "accepted_tos": True})


def test_login_locks_after_5_fails_then_success_clears():
    _fresh()
    with TestClient(app) as c:
        assert _signup(c, "bf_a@x.com").status_code == 201
        for _ in range(5):
            r = c.post("/api/v1/auth/login",
                       json={"email": "bf_a@x.com", "password": "wrong"})
            assert r.status_code == 401
        # 第 6 刀: 窗口锁死 — 连正确密码也得等 (锁的是尝试, 不泄露对错)
        r = c.post("/api/v1/auth/login",
                   json={"email": "bf_a@x.com", "password": "correct-horse1"})
        assert r.status_code == 429, r.text
        # 窗口内计数清掉 (模拟 15 分钟过去) → 正确密码进门, 且失败账本归零
        auth_mod._LOGIN_FAILS.clear()
        r = c.post("/api/v1/auth/login",
                   json={"email": "bf_a@x.com", "password": "correct-horse1"})
        assert r.status_code == 200, r.text
        assert not auth_mod._LOGIN_FAILS.get("bf_a@x.com")


def test_lock_is_per_email_not_global():
    _fresh()
    with TestClient(app) as c:
        assert _signup(c, "bf_b@x.com").status_code == 201
        assert _signup(c, "bf_c@x.com").status_code == 201
        for _ in range(5):
            c.post("/api/v1/auth/login",
                   json={"email": "bf_b@x.com", "password": "wrong"})
        # B 锁了, C 照常进门
        r = c.post("/api/v1/auth/login",
                   json={"email": "bf_c@x.com", "password": "correct-horse1"})
        assert r.status_code == 200, r.text


def test_signup_flood_capped_per_ip():
    _fresh()
    with TestClient(app) as c:   # TestClient 的 client.host 恒为 "testclient"
        for i in range(10):
            r = _signup(c, f"bf_flood_{i}@x.com")
            assert r.status_code == 201, r.text
        r = _signup(c, "bf_flood_last@x.com")
        assert r.status_code == 429, r.text
