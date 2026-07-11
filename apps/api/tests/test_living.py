# -*- coding: utf-8 -*-
"""🌍 活世界 P1: 世界心跳 + 缺席因果 (docs: Yi 2026-07-11 长期战略).

The heartbeat runs server-side while the player is AWAY: the clock turns, a
stood-up promise commits its consequence (rel drop + 大事记 + hurt text + news),
and the warmest character proposes a NEW dated meeting. On the comeback turn the
untold news plays as beats. Deterministic triggers; the model only writes words."""

from datetime import datetime, timedelta, timezone

from app.engine import living, relationships, runtime
from app.engine.llm import MockLLM

STORY = {
    "story": {"id": "s", "tuning": {"turns_per_slot": 1},
              "characters": [{"id": "a", "name": "甲", "is_lead": True},
                             {"id": "b", "name": "乙"}],
              "acts": [{"index": 1, "title": "一"}],
              "locations": [{"id": "hall", "name": "门厅", "detail": "一盏吊灯", "exits": ["后巷"]},
                            {"id": "alley", "name": "后巷", "detail": "潮湿", "exits": ["门厅"]}]},
    "secrets": [],
}


def _state(**over):
    st = runtime.default_state()
    st["met_ids"] = ["a", "b"]
    st.update(over)
    return st


def test_switch_and_due():
    st = _state()
    lc = living.set_living(st, True, 24)
    assert lc["on"] and lc["hours"] == 24 and lc["last"]
    assert not living.due(st)                      # just stamped → not due yet
    st["living"]["last"] = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    assert living.due(st)
    living.set_living(st, False)
    assert not living.is_on(st) and not living.due(st)
    # ended runs never tick
    st2 = _state(ended=True)
    living.set_living(st2, True)
    assert not living.due(st2)


def test_tick_advances_day_and_commits_absent_consequence():
    st = _state()
    living.set_living(st, True)
    st["promises"] = [{"char_id": "a", "char_name": "甲", "what": "夜里聊聊",
                       "day": 1, "slot": "夜", "location_id": "hall",
                       "romantic": True, "status": "open"}]
    st["clock"] = {"day": 1, "slot": 0, "turns_in_slot": 0}
    rel_before = relationships.new_scores()["closeness"]
    out = living.world_tick(STORY, st, MockLLM())
    assert out["advanced"] and st["clock"]["day"] == 2
    # ② the promise became a committed fact, not a stale row
    pr = st["promises"][0]
    assert pr["status"] == "missed" and pr["texted"] is True
    assert any(x["char_id"] == "a" for x in out["absent"])
    # the sting: relationship dropped
    assert st["rel"]["a"]["closeness"] < rel_before
    # the scene entered the ledgers: 大事记 + living_news + 手机
    assert any("你没来" in e["text"] for e in st["rel_log"]["a"])
    news = [n for n in st["living_news"] if n["kind"] == "absent"]
    assert news and news[0]["told"] is False and "甲" in news[0]["text"]
    th = ((st.get("phone") or {}).get("threads") or {}).get("a") or {}
    assert th.get("unread", 0) >= 1


def test_tick_generates_heartbeat_invite():
    st = _state()
    living.set_living(st, True)
    st["clock"] = {"day": 1, "slot": 0, "turns_in_slot": 0}
    out = living.world_tick(STORY, st, MockLLM())
    ev = out["event"]
    assert ev and ev["what"] == "去湖边走走"
    opened = [p for p in st["promises"] if p["status"] == "open"]
    assert len(opened) == 1 and opened[0]["char_id"] == ev["char_id"]
    assert any(n["kind"] == "invite" for n in st["living_news"])
    # the invite landed as a real unread message
    th = ((st.get("phone") or {}).get("threads") or {}).get(ev["char_id"]) or {}
    assert th.get("unread", 0) >= 1
    # tick restamps `last` → not due again immediately
    assert not living.due(st)


def test_clock_off_and_ended_refuse():
    off = {"story": {**STORY["story"], "tuning": {"turns_per_slot": 0}}, "secrets": []}
    st = _state()
    living.set_living(st, True)
    assert living.world_tick(off, st, MockLLM())["advanced"] is False
    st2 = _state(ended=True)
    assert living.world_tick(STORY, st2, MockLLM())["advanced"] is False


def test_comeback_turn_tells_news_once():
    st = _state()
    living.set_living(st, True)
    st["living_news"] = [{"day": 2, "kind": "absent", "char_id": "a", "name": "甲",
                          "text": "甲把杯子倒扣在桌上，先走了。", "told": False}]
    told = living.serve_living_news(st)
    assert told == ["甲把杯子倒扣在桌上，先走了。"]
    assert living.serve_living_news(st) == []      # told exactly once
    # and through the real turn pipeline it lands as a beat
    st2 = _state()
    st2["living_news"] = [{"day": 2, "kind": "invite", "char_id": "a", "name": "甲",
                           "text": "甲约了你明天夜：去湖边走走。", "told": False}]
    out = runtime.run_turn(STORY, st2, {"name": "我"}, "我回来了", channel="say", llm=MockLLM())
    assert any("你不在的时候" in (b.get("text") or "") for b in out["beats"])
    assert all(n["told"] for n in out["state"]["living_news"])
