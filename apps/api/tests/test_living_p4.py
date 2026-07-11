# -*- coding: utf-8 -*-
"""🌌 活世界 P4: 纪念日 + 跨存档残响."""
from app.engine import living, relationships, runtime
from app.engine.llm import MockLLM

STORY = {
    "story": {"id": "s", "tuning": {"turns_per_slot": 1, "phone": 1},
              "characters": [{"id": "a", "name": "甲", "is_lead": True},
                             {"id": "b", "name": "乙"}],
              "acts": [{"index": 1, "title": "一"}],
              "locations": [{"id": "hall", "name": "门厅", "detail": "一盏吊灯",
                             "exits": []}]},
    "secrets": [],
}


def _warm(st, cid, closeness=60):
    sc = relationships.new_scores()
    sc["closeness"] = closeness
    st.setdefault("rel", {})[cid] = sc


def test_anniversary_fires_on_month_mark_and_replaces_invite():
    st = runtime.default_state()
    st["met_ids"] = ["a"]
    st["clock"] = {"day": 30, "slot": 0, "turns_in_slot": 0}
    st["anniv_met"] = {"a": 1}   # 认识于第1天 → 第31天 = 满月
    _warm(st, "a")
    out = living.world_tick(STORY, st, MockLLM())
    assert out["anniv"] and out["anniv"]["char_id"] == "a" and out["anniv"]["months"] == 1
    assert out["event"] is None, "纪念日当天不发普通邀约"
    kinds = [n.get("kind") for n in st.get("living_news") or []]
    assert "anniv" in kinds
    thread = ((st.get("phone") or {}).get("threads") or {}).get("a") or {}
    assert thread.get("msgs"), "纪念日短信落进小手机"


def test_anniversary_needs_warmth():
    st = runtime.default_state()
    st["met_ids"] = ["a"]
    st["clock"] = {"day": 30, "slot": 0, "turns_in_slot": 0}
    st["anniv_met"] = {"a": 1}
    out = living.world_tick(STORY, st, MockLLM())   # 没热度 → 不过纪念日
    assert out["anniv"] is None


def test_anniversary_baseline_backfills_met_ids():
    st = runtime.default_state()
    st["met_ids"] = ["a", "b"]
    st["clock"] = {"day": 5, "slot": 0, "turns_in_slot": 0}
    living.world_tick(STORY, st, MockLLM())
    assert set(st["anniv_met"]) == {"a", "b"}


def test_echo_line_only_for_echo_chars():
    st = runtime.default_state()
    st["echo"] = {"from_run": "r0", "chars": ["a"]}
    assert "既视感" in runtime.echo_line(STORY, st, "a")
    assert runtime.echo_line(STORY, st, "b") == ""
    assert runtime.echo_line(STORY, {}, "a") == ""
