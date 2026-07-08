# -*- coding: utf-8 -*-
"""⚡ 修为数值账本: story-defined ladder, training twin with diminishing returns,
risky breakthrough ritual, offline trickle, anchor law."""
from app.engine import runtime

SB = {"story": {"id": "cx", "sandbox": {"enabled": True,
                "progression": {"name": "斗气", "ranks": ["斗之气", "斗者", "斗师"]}},
                "characters": [], "acts": [{"index": 1}],
                "locations": [{"id": "l1", "name": "静室", "exits": []}]},
      "secrets": []}
PLAIN = {"story": {"id": "px", "characters": [], "acts": [{"index": 1}],
                   "locations": []}, "secrets": []}


def _st():
    return {**runtime.default_state(), "location_id": "l1"}


def test_train_gains_and_diminishes():
    st = _st()
    r1 = runtime.player_train(SB, st, "我盘膝修炼", channel="do")
    assert r1 and r1["gain"] >= 2 and st["cult"]["prog"] == r1["prog"]
    g1 = r1["gain"]
    # grind twice more: streak halves the base
    runtime.player_train(SB, st, "继续修炼", channel="do")
    r3 = runtime.player_train(SB, st, "继续苦修", channel="do")
    assert r3["gain"] <= g1


def test_no_ladder_no_op():
    st = _st()
    assert runtime.player_train(PLAIN, st, "我盘膝修炼", channel="do") is None
    assert runtime.cult_view(PLAIN, st) is None
    assert runtime.cult_anchor(PLAIN, st) == ""


def test_breakthrough_requires_full_bottleneck():
    st = _st()
    st["cult"] = {"rank": 0, "prog": 40, "streak": 0}
    r = runtime.player_breakthrough(SB, st, "我要突破", channel="do")
    assert r and r.get("not_ready") and st["cult"]["rank"] == 0


def test_breakthrough_success_and_fail(monkeypatch):
    st = _st()
    st["cult"] = {"rank": 0, "prog": 100, "streak": 2}
    monkeypatch.setattr(runtime.random, "randint", lambda a, b: 20)
    r = runtime.player_breakthrough(SB, st, "突破", channel="do")
    assert r["success"] and r["crit"] and st["cult"] == {"rank": 1, "prog": 20, "streak": 0}
    st["cult"] = {"rank": 1, "prog": 100, "streak": 0}
    monkeypatch.setattr(runtime.random, "randint", lambda a, b: 3)
    r2 = runtime.player_breakthrough(SB, st, "冲击瓶颈", channel="do")
    assert r2["success"] is False and st["cult"]["rank"] == 1 and st["cult"]["prog"] == 60


def test_capped_at_summit():
    st = _st()
    st["cult"] = {"rank": 2, "prog": 100, "streak": 0}
    r = runtime.player_breakthrough(SB, st, "突破", channel="do")
    assert r.get("capped")
    v = runtime.cult_view(SB, st)
    assert v["cap"] and not v["ready"]


def test_offline_trickle_caps_at_bottleneck():
    st = _st()
    st["cult"] = {"rank": 0, "prog": 95, "streak": 3}
    g = runtime.cult_offline_gain(SB, st, away_hours=24)
    assert g > 0 and st["cult"]["prog"] == 100 and st["cult"]["streak"] == 0
    # already full → nothing
    assert runtime.cult_offline_gain(SB, st, away_hours=24) == 0


def test_anchor_states_rank_and_law():
    st = _st()
    st["cult"] = {"rank": 1, "prog": 100, "streak": 0}
    a = runtime.cult_anchor(SB, st)
    assert "斗者" in a and "突破" in a and "碾压" in a
