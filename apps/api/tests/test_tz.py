# -*- coding: utf-8 -*-
"""⏰ 时区对齐 (Yi 2026-08-04:「要对齐时区…不管是星期还是日期都按照玩家的时区走」)。

日历完全是玩家的日历: day / slot / 星期 / 月日 / 季节 都按 state["tz"] 算。
年代是另一件事, 一个字段都不共用 —— 这里只管日历。

两条设计上的钉子, 拆掉哪一条都会静默出错:
  ① 协议里【不存在偏移数字】, 只传 IANA 名。JS 的 getTimezoneOffset() 符号是反的
     (上海返回 -480), 而冻结的偏移一遇夏令时就错整整半年。
  ② day 只增不减。_time_index = day*3+slot 是全船约定/心事/court 的时间轴, 一倒退,
     到期的约定会在 open↔missed 之间来回翻面, 纪念日会二次触发。
"""
from datetime import timedelta

from app.engine import runtime

# ⚠️ conftest 的 autouse fixture 会把 real_clock 按到 0, 这里必须显式开
BASE = {"story": {"id": "s", "tuning": {"turns_per_slot": 6, "real_clock": 1},
                  "characters": [{"id": "a", "name": "阿珍", "is_lead": True}],
                  "acts": [{"index": 1, "title": "一"}]},
        "secrets": []}


def _sync(tz):
    st = runtime.default_state()
    if tz is not None:
        st["tz"] = tz
    runtime.sync_real_clock(BASE, st)
    return st


def _expect(tz):
    """拿 _now() 自己对表, 不写死数字 —— 写死了开发机换时区就恒红。"""
    from zoneinfo import ZoneInfo
    return runtime._now().astimezone(ZoneInfo(tz))


# ── ① 日历跟玩家走 ────────────────────────────────────────────────────────
def test_the_calendar_follows_the_players_timezone():
    st = _sync("America/Los_Angeles")
    want = _expect("America/Los_Angeles")
    ck = st["clock"]
    assert ck["date"] == f"{want.month}月{want.day}日", "月日不是玩家那边的"
    assert ck["wd"] == f"星期{'一二三四五六日'[want.weekday()]}", "星期不是玩家那边的"
    assert ck["real"] == f"{want.hour:02d}:{want.minute:02d}", "时刻不是玩家那边的"
    assert ck["slot"] == (0 if 5 <= want.hour < 12 else (1 if 12 <= want.hour < 18 else 2))


def test_the_ui_clock_chip_uses_the_same_reading_as_the_prompt():
    """只改一处不改另一处 = 顶栏挂着错牌, 而角色拿着另一个时辰开口。栽过一次。"""
    st = _sync("America/New_York")
    view = runtime.clock_view(BASE, st)
    assert view["hhmm"] == st["clock"]["real"]


# ── ② 老档一格不动 ────────────────────────────────────────────────────────
def test_a_save_with_no_timezone_reads_exactly_like_before():
    st = _sync(None)
    now = runtime._now()
    assert st["clock"]["date"] == f"{now.month}月{now.day}日"
    assert st["clock"]["real"] == f"{now.hour:02d}:{now.minute:02d}"
    assert "tz_bad" not in st


def test_a_junk_timezone_falls_back_to_the_server_and_leaves_a_trace():
    """静默漂移比报错更难查 —— 退回去可以, 但必须留下痕迹。"""
    st = _sync("Mars/Olympus")
    now = runtime._now()
    assert st["clock"]["real"] == f"{now.hour:02d}:{now.minute:02d}"
    assert st.get("tz_bad") == "Mars/Olympus"


# ── ③ 符号钉死 ────────────────────────────────────────────────────────────
def test_the_sign_convention_is_pinned():
    """上海是 UTC+8。JS 的 getTimezoneOffset() 在上海返回 -480 —— 谁哪天把偏移数字
    塞回协议里, 这条会当场红。"""
    assert runtime._now_for({"tz": "Asia/Shanghai"}).utcoffset() == timedelta(hours=8)
    assert runtime._now_for({"tz": "America/Los_Angeles"}).utcoffset() in (
        timedelta(hours=-8), timedelta(hours=-7))   # 夏令时两种都对


def test_a_naive_now_is_not_silently_reinterpreted(monkeypatch):
    """monkeypatch 给 naive datetime 时不许当成本地时间瞎解释。"""
    from datetime import datetime
    monkeypatch.setattr(runtime, "_now", lambda: datetime(2026, 8, 4, 12, 0))
    assert runtime._now_for({}).utcoffset() == timedelta(hours=8)
    assert runtime._now_for({"tz": "Asia/Shanghai"}).hour == 12


# ── ④ day 只增不减 ────────────────────────────────────────────────────────
def test_the_day_counter_never_walks_backwards():
    st = runtime.default_state()
    st["real_epoch"] = runtime._now().date().isoformat()
    st["clock"] = {"day": 20, "slot": 0, "turns_in_slot": 0}
    st["tz"] = "Pacific/Kiritimati"      # 最东 (+14)
    runtime.sync_real_clock(BASE, st)
    d_east = st["clock"]["day"]
    st["tz"] = "Pacific/Midway"          # 最西 (-11)
    runtime.sync_real_clock(BASE, st)
    assert st["clock"]["day"] >= d_east >= 20, "day 倒流会让约定在 open↔missed 之间翻面"


def test_a_fresh_run_still_starts_on_day_one():
    """护栏只挡倒退, 不许把新档顶成第 20 天。"""
    st = _sync("America/New_York")
    assert st["clock"]["day"] == 1


# ── ⑤ 英文本子仍然零中文 ──────────────────────────────────────────────────
def test_an_english_story_keeps_its_calendar_in_english():
    en = {"story": {**BASE["story"], "language": "en"}, "secrets": []}
    st = runtime.default_state()
    st["tz"] = "America/New_York"
    runtime.sync_real_clock(en, st)
    ck = st["clock"]
    assert not runtime.has_cjk(ck["wd"] + ck["date"] + ck["season"]), \
        "en 本子的 state 里不许留中文 (lang-contract)"
