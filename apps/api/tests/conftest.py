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
def _schema_is_always_there():
    """🧱 每个用例开跑前把缺的表补回来。

    全套件共用一个 SQLite 文件 (test_e2e.db), 而十来个测试文件为了拿干净数据会
    `Base.metadata.drop_all()` —— 于是【跑在它们后面】的用例可能撞上 no such table。
    pytest-randomly 每次换种子, 受害者就跟着轮换: 同一份代码这一跑 917 绿, 下一跑
    17 红, 而红的那些跟改动毫无关系 (实弹 2026-08-04: 先是 test_shared_library,
    换个种子变成 test_shelf_tidy)。

    这正是「测试基线不是零」最难查的那一层: 它伪装成随机故障, 让人以为是自己改坏了。
    create_all 带 checkfirst, 表都在时是纯 no-op, 代价可以忽略。
    """
    from sqlalchemy import inspect

    from app.db import Base, engine
    # 先把 inspector 缓存清掉再建表: drop_all 之后缓存里可能还记着「表在」,
    # create_all(checkfirst=True) 一查缓存就跳过创建, 于是表真的没回来。
    inspect(engine).clear_cache()
    Base.metadata.create_all(bind=engine)


@pytest.fixture(autouse=True)
def _fictional_clock_default(monkeypatch):
    monkeypatch.setitem(runtime.DEFAULT_TUNING, "real_clock", 0)
    # 剧组戏眼同理: 生产全舰开, 测试世界默认关 (spy LLM 的 prompts[0] 执法点生态), 剧组测试显式开旗
    monkeypatch.setitem(runtime.DEFAULT_TUNING, "troupe", 0)


@pytest.fixture
def map_writes_on(monkeypatch):
    """🔒 把 2026-08-04 那把【旧的整锁】完全打开 —— 移动 + 铸造两半都开。

    ⚠️ 2026-08-08 起这把锁拆成了两个 (Yi:「模型决定」):
        LLM_MAP_WRITES   谁在哪 —— 已默认 True，模型说了算
        LLM_MINTS_PLACES 有哪些地方 —— 仍是 False
    老用例挂的是「整锁」的语义 (它们测的多半是铸造那条路)，所以这个夹具两个都开，
    保持它们原来测的东西不变。只想开铸造那一半的用例请用 mints_on。
    """
    monkeypatch.setattr(runtime, "LLM_MAP_WRITES", True)
    monkeypatch.setattr(runtime, "LLM_MINTS_PLACES", True)


@pytest.fixture
def mints_on(monkeypatch):
    """只开【铸造新地点】那一半 (runtime.LLM_MINTS_PLACES)。"""
    monkeypatch.setattr(runtime, "LLM_MINTS_PLACES", True)


@pytest.fixture
def map_writes_off(monkeypatch):
    """把「谁在哪」收回引擎手里 —— 守可逆合同: 锁一关，提示词层必须跟着换说法。"""
    monkeypatch.setattr(runtime, "LLM_MAP_WRITES", False)


@pytest.fixture
def typed_move_on(monkeypatch):
    """开回打字移动 (runtime.TYPED_MOVE, Yi 2026-08-04 定默认关)。

    产品行为: 换场只走地图面板, 输入框里写「我去码头」不算数。测【打字移动本身】
    的用例显式开旗跑 —— 与 map_writes_on 同理, 是休眠代码的回归网。
    """
    monkeypatch.setattr(runtime, "TYPED_MOVE", True)


@pytest.fixture
def invite_move_on(monkeypatch):
    """显式开「台词里的邀约 → 确认条」(runtime.INVITE_MOVE)。

    ⚠️ 2026-08-08 起这把锁【默认就是开的】(见 runtime 那一段的原委), 所以这个夹具现在
    是个 no-op 保险 —— 留着是为了让老用例的意图仍然读得出来, 也为了万一再关时它们
    自己会红。要测「关着时」请用 invite_move_off。
    """
    monkeypatch.setattr(runtime, "INVITE_MOVE", True)


@pytest.fixture
def invite_move_off(monkeypatch):
    """关掉邀约确认条 —— 守可逆合同: 锁一关, 提示词层必须跟着换说法, 不许一边不收
    move_invite 一边还教模型申报 (那就是 2026-08-06 的半吊子锁)。"""
    monkeypatch.setattr(runtime, "INVITE_MOVE", False)


@pytest.fixture
def golden_auto_on(monkeypatch):
    """开回金色瞬间的【自动摇骰】(tuning.golden_chance, Yi 2026-08-04 定缺省 0)。

    产品行为: 不再每回合白摇 —— 那一版只读本回合最后四句, 写出来的东西不认得玩家
    走过的路。改成玩家自己点 (runtime.golden_moment_now), 那一次喂足最近几十拍。
    测【自动摇骰本身】的用例显式开旗跑, 与 map_writes_on / typed_move_on 同理。
    """
    monkeypatch.setitem(runtime.DEFAULT_TUNING, "golden_chance", 4)


@pytest.fixture
def seek_automint_on(monkeypatch):
    """开回「找人自动造真」(runtime.SEEK_AUTO_MINT, Yi 2026-08-05 定缺省关)。

    产品行为: 玩家提到册子上没有的名字, 不再由 scout_char 判官代拍板当场造人 ——
    名字交给导演, 由它读着整场上下文判断该不该有这号人。测那套判官管线本身的用例
    显式开旗跑, 与 map_writes_on / typed_move_on / golden_auto_on 同理。
    """
    monkeypatch.setattr(runtime, "SEEK_AUTO_MINT", True)
