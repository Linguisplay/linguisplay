# -*- coding: utf-8 -*-
"""🔕 静默时段撞上心跳: 改期, 不是丢弃 (2026-08-04 修)。

病根: 心跳是 600 秒轮询 + 纯 UTC 差值判到期, 所以它每天都落在几乎同一个钟点
(每天前漂 ≤10 分钟, 要 54 天才漂出一个 9 小时的静默窗)。一个存档的间隔一旦落进
静默时段, 那个玩家的推送就是【永久】归零 —— 消息照进小手机, 但没人知道。

顺带修了纪念日: 原来判 `span % 30` 精确等值, 心跳一旦覆盖不止一天 (补算/长时间
没来/时区抖动), 天数从 29 直接跳到 31, 那个满月就永远错过。
"""
from datetime import datetime, timedelta, timezone

from app import webpush
from app.engine import living


def _on(hours=24):
    st = {"living": {"on": True, "hours": hours, "last": "2026-08-01T00:00:00+00:00"}}
    return st


# ── 静默判定跟玩家走 ──────────────────────────────────────────────────────
def test_quiet_hours_are_judged_in_the_players_own_timezone():
    """同一个 UTC 时刻, 北京的深夜正是纽约的下午。从前全船按北京算。"""
    utc = datetime(2026, 8, 4, 18, 0, tzinfo=timezone.utc)   # 北京 8/5 02:00
    from zoneinfo import ZoneInfo
    assert webpush.quiet_now(utc.astimezone(ZoneInfo("Asia/Shanghai"))) is True
    ny = utc.astimezone(ZoneInfo("America/New_York"))        # 纽约 8/4 14:00
    assert webpush.quiet_now(ny) is False, "纽约的下午两点不该算深夜"


def test_an_unknown_timezone_falls_back_to_the_server_clock():
    for junk in ("", "Mars/Olympus", "  "):
        assert isinstance(webpush.quiet_now(tz=junk), bool)


# ── 改期而不是丢弃 ────────────────────────────────────────────────────────
def test_a_quiet_heartbeat_reschedules_instead_of_vanishing():
    st = _on(hours=24)
    assert living.defer_to_friendly_hour(st, "America/New_York") is True
    nxt = (datetime.fromisoformat(st["living"]["last"]) + timedelta(hours=24))
    from zoneinfo import ZoneInfo
    local = nxt.astimezone(ZoneInfo("America/New_York"))
    assert local.hour == 19, "下一次心跳没落在玩家本地的傍晚"
    assert nxt > datetime.now(timezone.utc), "改期改到了过去 — 下一拍会立刻再撞一次"


def test_rescheduling_lands_outside_the_quiet_window():
    """改完期还落在静默里 = 白改。"""
    st = _on()
    living.defer_to_friendly_hour(st, "America/New_York")
    nxt = datetime.fromisoformat(st["living"]["last"]) + timedelta(hours=24)
    from zoneinfo import ZoneInfo
    assert webpush.quiet_now(nxt.astimezone(ZoneInfo("America/New_York"))) is False


def test_it_respects_a_custom_heartbeat_interval():
    st = _on(hours=6)
    living.defer_to_friendly_hour(st, "Asia/Shanghai")
    nxt = datetime.fromisoformat(st["living"]["last"]) + timedelta(hours=6)
    from zoneinfo import ZoneInfo
    assert nxt.astimezone(ZoneInfo("Asia/Shanghai")).hour == 19


def test_a_run_with_the_living_world_off_is_left_alone():
    st = {"living": {"on": False}}
    assert living.defer_to_friendly_hour(st, "Asia/Shanghai") is False
    assert st["living"] == {"on": False}
    assert living.defer_to_friendly_hour({}, "") is False


def test_a_junk_timezone_still_reschedules_just_on_server_time():
    st = _on()
    assert living.defer_to_friendly_hour(st, "Mars/Olympus") is True
    assert datetime.fromisoformat(st["living"]["last"]) < datetime.now(timezone.utc)


# ── 纪念日不再被跳过 ──────────────────────────────────────────────────────
def _anniv_fires(prev_day, day, met_day=1):
    """复刻 world_tick 里那段判定 (span//30 跨越制)。"""
    span = day - met_day
    prev_span = max(0, prev_day - met_day)
    return span > 0 and span // 30 > prev_span // 30


def test_the_monthly_mark_survives_a_heartbeat_that_covered_several_days():
    assert _anniv_fires(30, 31), "正常推进的满月"
    assert _anniv_fires(29, 32), "跨过去的满月 — 旧的 span%30 会永远错过它"
    assert _anniv_fires(58, 62), "第二个满月同样"


def test_it_does_not_fire_twice_for_the_same_month():
    assert not _anniv_fires(31, 32)
    assert not _anniv_fires(35, 40)


def test_it_does_not_fire_before_the_first_month():
    assert not _anniv_fires(1, 29)
    assert not _anniv_fires(0, 1)
