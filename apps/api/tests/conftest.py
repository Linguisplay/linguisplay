# -*- coding: utf-8 -*-
"""测试世界的时钟法 (2026-07-26 现实对齐升格全舰时立):
生产默认 real_clock=1 (故事时间=真实时间, Yi 定); 但存量测试生态建立在虚构时钟上 —
22 个文件预设 slot/day 当执法点。测试世界默认虚构钟, 现实对齐机制由
tests/test_real_clock.py 显式开旗执法。沙盒的现实同步老合同不受此旗影响。"""
import os
import sys
import types

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

# 🪟 Windows 垫片: runs.py 顶层 import fcntl (Unix 专属) — 本地 Windows 跑不了任何
# 走 app.main 的测试 (13 个模块收集即炸)。锁语义在单进程测试里本就无争用, 垫空实现。
if sys.platform == "win32" and "fcntl" not in sys.modules:
    _fcntl = types.ModuleType("fcntl")
    _fcntl.LOCK_EX, _fcntl.LOCK_SH, _fcntl.LOCK_UN, _fcntl.LOCK_NB = 2, 1, 8, 4
    _fcntl.flock = lambda *a, **k: None
    _fcntl.lockf = lambda *a, **k: None
    sys.modules["fcntl"] = _fcntl

import pytest  # noqa: E402

from app.engine import runtime  # noqa: E402


@pytest.fixture(autouse=True)
def _fictional_clock_default(monkeypatch):
    monkeypatch.setitem(runtime.DEFAULT_TUNING, "real_clock", 0)
    # 剧组戏眼同理: 生产全舰开, 测试世界默认关 (spy LLM 的 prompts[0] 执法点生态), 剧组测试显式开旗
    monkeypatch.setitem(runtime.DEFAULT_TUNING, "troupe", 0)


@pytest.fixture
def map_writes_on(monkeypatch):
    """🔒 解开「对话改地图」的锁 (runtime.LLM_MAP_WRITES, Yi 2026-08-04 定默认关)。

    产品行为是关的 —— 对话不许铸新场景、不许把人挪到场景。但那套代码还在, 留着可逆,
    所以测它【本身】的用例显式开旗跑: 它们是这套休眠代码的回归网, 哪天翻回 True 才不
    会一片废墟。

    ⚠️ 新写的用例别顺手挂这个。默认关才是玩家看到的行为, 挂上就测不到真实产品了。
    """
    monkeypatch.setattr(runtime, "LLM_MAP_WRITES", True)
