# -*- coding: utf-8 -*-
"""⚡ 修为数值账本: story-defined ladder with 小境界/资质/战力, resource-fed training,
sub-stage vs 天劫 breakthroughs, offline trickle, and 境界碾压 at the dice."""
from app.engine import runtime

SB = {"story": {"id": "cx", "sandbox": {"enabled": True,
                "progression": {"name": "斗气", "ranks": ["斗之气", "斗者", "斗师"]}},
                "characters": [], "acts": [{"index": 1}],
                "locations": [{"id": "l1", "name": "静室", "detail": "一间寻常静室", "exits": []}]},
      "secrets": []}
PLAIN = {"story": {"id": "px", "characters": [], "acts": [{"index": 1}],
                   "locations": []}, "secrets": []}


def _st(**cult):
    s = {**runtime.default_state(), "location_id": "l1"}
    if cult:
        s["cult"] = {"rank": 0, "stage": 0, "prog": 0, "streak": 0, "apt": "中平之资", **cult}
    return s


def test_first_training_rolls_aptitude():
    st = _st()
    r = runtime.player_train(SB, st, "我盘膝修炼", channel="do")
    assert r and r.get("apt_new") and st["cult"]["apt"] == r["apt_new"]
    assert r["gain"] >= 2 and st["cult"]["prog"] == r["prog"]


def test_no_ladder_no_op():
    st = _st()
    assert runtime.player_train(PLAIN, st, "我盘膝修炼", channel="do") is None
    assert runtime.cult_view(PLAIN, st) is None
    assert runtime.cult_anchor(PLAIN, st) == ""
    assert runtime.cult_action_mod(PLAIN, st, "强攻") == 0


def test_resource_consumed_boosts_training():
    st = _st(prog=10)
    st["inventory"] = [{"name": "聚气丹"}]
    r = runtime.player_train(SB, st, "我服下聚气丹打坐", channel="do")
    assert r["consumed"] == "聚气丹" and "服聚气丹" in (r["why"] or [])
    assert not any(i["name"] == "聚气丹" for i in st["inventory"])   # eaten
    assert r["gain"] >= 12


def test_spirit_place_bonus():
    world = {"story": {**SB["story"], "locations": [
        {"id": "l1", "name": "灵泉洞", "detail": "洞中灵气充裕，灵泉汩汩", "exits": []}]},
        "secrets": []}
    st = _st(prog=10)
    r = runtime.player_train(world, st, "我打坐吐纳", channel="do")
    assert "灵气充裕" in (r["why"] or [])


def test_substage_breakthrough_is_forgiving(monkeypatch):
    st = _st(stage=0, prog=100)
    monkeypatch.setattr(runtime.random, "randint", lambda a, b: 6)   # ≥6 clears a sub-step
    r = runtime.player_breakthrough(SB, st, "我要突破", channel="do")
    assert r["success"] and not r["major"] and st["cult"]["stage"] == 1


def test_major_crossing_is_the_tribulation(monkeypatch):
    st = _st(stage=3, prog=100)   # 圆满 → next major realm
    monkeypatch.setattr(runtime.random, "randint", lambda a, b: 6)   # 6 < 12 → 天劫 fails
    r = runtime.player_breakthrough(SB, st, "我要渡劫突破", channel="do")
    assert r["success"] is False and r["major"] and st["cult"]["rank"] == 0
    st2 = _st(stage=3, prog=100)
    monkeypatch.setattr(runtime.random, "randint", lambda a, b: 19)  # 19 ≥ 12 → ascend + 顿悟
    r2 = runtime.player_breakthrough(SB, st2, "渡劫", channel="do")
    assert r2["success"] and r2["major"] and r2["crit"]
    assert st2["cult"] == {"rank": 1, "stage": 0, "prog": 25, "streak": 0, "apt": "中平之资"}


def test_breakthrough_requires_full_bottleneck():
    st = _st(prog=40)
    r = runtime.player_breakthrough(SB, st, "我要突破", channel="do")
    assert r and r.get("not_ready")


def test_capped_at_summit():
    st = _st(rank=2, stage=3, prog=100)   # top realm, 圆满
    assert runtime.player_breakthrough(SB, st, "突破", channel="do").get("capped")
    v = runtime.cult_view(SB, st)
    assert v["cap"] and not v["ready"]


def test_power_grows_with_rank():
    low = runtime.cult_power(SB, _st(rank=0, stage=0))
    high = runtime.cult_power(SB, _st(rank=2, stage=3))
    assert high > low * 3   # 境界碾压: realms dwarf each other numerically


def test_cultivation_lowers_physical_dc():
    st = _st(rank=2, stage=2)               # high realm
    assert runtime.cult_action_mod(SB, st, "强攻") < 0   # physical feats get easier
    assert runtime.cult_action_mod(SB, st, "欺瞒") == 0  # lying doesn't scale with realm


def test_offline_needs_aptitude_and_caps():
    # no aptitude yet (never trained) → no offline gain
    st_raw = _st()
    st_raw["cult"] = {"rank": 0, "stage": 0, "prog": 50, "streak": 0, "apt": None}
    assert runtime.cult_offline_gain(SB, st_raw, away_hours=24) == 0
    # with aptitude → trickles, capped at the bottleneck
    st = _st(prog=95)
    g = runtime.cult_offline_gain(SB, st, away_hours=24)
    assert g > 0 and st["cult"]["prog"] == 100
    assert runtime.cult_offline_gain(SB, st, away_hours=24) == 0   # full → nothing


def test_anchor_states_stage_power_and_law():
    st = _st(rank=1, stage=2, prog=100)
    a = runtime.cult_anchor(SB, st)
    assert "斗者" in a and "后期" in a and "战力" in a and "碾压" in a and "突破" in a
