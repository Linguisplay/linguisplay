# -*- coding: utf-8 -*-
"""SQLite 并发地基 (台账 P2): 每个连接必须带 WAL + busy_timeout —
双人同时开局撞 database is locked 直接崩回合的实弹。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from sqlalchemy import text  # noqa: E402

from app.db import engine  # noqa: E402


def test_sqlite_connection_has_wal_and_busy_timeout():
    with engine.connect() as c:
        assert str(c.execute(text("PRAGMA journal_mode")).scalar()).lower() == "wal"
        assert int(c.execute(text("PRAGMA busy_timeout")).scalar()) == 5000
