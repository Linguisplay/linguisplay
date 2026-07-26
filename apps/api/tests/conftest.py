# -*- coding: utf-8 -*-
"""测试世界的时钟法 (2026-07-26 现实对齐升格全舰时立):
生产默认 real_clock=1 (故事时间=真实时间, Yi 定); 但存量测试生态建立在虚构时钟上 —
22 个文件预设 slot/day 当执法点。测试世界默认虚构钟, 现实对齐机制由
tests/test_real_clock.py 显式开旗执法。沙盒的现实同步老合同不受此旗影响。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

import pytest  # noqa: E402

from app.engine import runtime  # noqa: E402


@pytest.fixture(autouse=True)
def _fictional_clock_default(monkeypatch):
    monkeypatch.setitem(runtime.DEFAULT_TUNING, "real_clock", 0)
