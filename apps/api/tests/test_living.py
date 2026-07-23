# -*- coding: utf-8 -*-
"""🌍 活世界 P1: 世界心跳 + 缺席因果 (docs: Yi 2026-07-11 长期战略).

⚖️ 无点击不推进 (Yi 2026-07-14 拍板) 后的新契约: 心跳只做状态数学 (时钟/掉分/
promise 翻转) 并把「该演的」押成词债 (living_news.pend); 戏文/带刺短信/邀约
全部等玩家亲手点开的回合由 settle_pending 补演, 再经 serve_living_news 播报."""

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


def test_tick_advances_day_and_stages_absent_consequence():
    st = _state()
    living.set_living(st, True)
    st["promises"] = [{"char_id": "a", "char_name": "甲", "what": "夜里聊聊",
                       "day": 1, "slot": "夜", "location_id": "hall",
                       "romantic": True, "status": "open"}]
    st["clock"] = {"day": 1, "slot": 0, "turns_in_slot": 0}
    rel_before = relationships.new_scores()["closeness"]
    out = living.world_tick(STORY, st)
    assert out["advanced"] and st["clock"]["day"] == 2
    # ② the promise became a committed fact, not a stale row
    pr = st["promises"][0]
    assert pr["status"] == "missed" and pr["texted"] is True
    assert any(x["char_id"] == "a" for x in out["absent"])
    # the sting: relationship dropped (纯数学, 心跳当场落账)
    assert st["rel"]["a"]["closeness"] < rel_before
    # ⚖️ 只攒不演: 戏文与短信是词债 — 大事记未写, 手机没响, news 押着 pend
    assert not (st.get("rel_log") or {}).get("a")
    assert not ((st.get("phone") or {}).get("threads") or {}).get("a")
    news = [n for n in st["living_news"] if n["kind"] == "absent"]
    assert news and news[0]["told"] is False and news[0]["pend"]["text_due"] is True
    # 词债补演 (玩家点开的回合): 戏文入大事记, 带刺短信送达
    events = living.settle_pending(STORY, st, MockLLM())
    assert any("你没来" in e["text"] for e in st["rel_log"]["a"])
    assert news[0]["text"] and "pend" not in news[0]
    th = ((st.get("phone") or {}).get("threads") or {}).get("a") or {}
    assert th.get("unread", 0) >= 1 and events


def test_tick_stages_heartbeat_invite_settle_books_it():
    st = _state()
    living.set_living(st, True)
    st["clock"] = {"day": 1, "slot": 0, "turns_in_slot": 0}
    # 📇 新法: 没交换过联系方式的人联系不上你 — 心跳一个约也发不出
    cold = living.world_tick(STORY, {**st, "living": dict(st["living"])})
    assert cold["event"] is None
    st["contact_ids"] = list(st.get("met_ids") or [])
    out = living.world_tick(STORY, st)
    # ⚖️ 心跳只选角押债: 推送模板只需要人名; 约本身还没订, 手机也还没响
    assert out["event"] and out["event"]["name"] == "甲"
    assert not [p for p in st["promises"] if p.get("status") == "open"]
    assert not ((st.get("phone") or {}).get("threads") or {})
    nw = next(n for n in st["living_news"] if n["kind"] == "invite")
    assert nw["pend"]["invite_due"] and not nw["text"]
    # settle: 邀约写词 + make_promise 正账 + 短信送达
    events = living.settle_pending(STORY, st, MockLLM())
    opened = [p for p in st["promises"] if p["status"] == "open"]
    assert len(opened) == 1 and opened[0]["char_id"] == out["event"]["char_id"]
    assert "去湖边走走" in nw["text"] and "pend" not in nw
    th = ((st.get("phone") or {}).get("threads") or {}).get(out["event"]["char_id"]) or {}
    assert th.get("unread", 0) >= 1 and events
    # tick restamps `last` → not due again immediately
    assert not living.due(st)


def test_clock_off_and_ended_refuse():
    off = {"story": {**STORY["story"], "tuning": {"turns_per_slot": 0}}, "secrets": []}
    st = _state()
    living.set_living(st, True)
    assert living.world_tick(off, st)["advanced"] is False
    st2 = _state(ended=True)
    assert living.world_tick(STORY, st2)["advanced"] is False


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


def test_pipeline_settles_staged_debt_into_beat_and_phone():
    """词债走真回合管线: 心跳押的 absent 债, 玩家一拍下去 → 戏文播报 + 短信事件."""
    st = _state()
    living.set_living(st, True)
    st["promises"] = [{"char_id": "a", "char_name": "甲", "what": "夜里聊聊",
                       "day": 1, "slot": "夜", "location_id": "hall",
                       "romantic": False, "status": "open"}]
    st["clock"] = {"day": 1, "slot": 0, "turns_in_slot": 0}
    living.world_tick(STORY, st)
    out = runtime.run_turn(STORY, st, {"name": "我"}, "我回来了", channel="say", llm=MockLLM())
    assert any("你不在的时候" in (b.get("text") or "") for b in out["beats"])
    th = ((out["state"].get("phone") or {}).get("threads") or {}).get("a") or {}
    assert th.get("unread", 0) >= 1
