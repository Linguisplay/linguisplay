# -*- coding: utf-8 -*-
"""🛡 信任/戒备轴 (合伙人 2026-08-02): 慢建快塌 + 行为学三档 + 法条五元组。"""
from app.engine import relationships as rel
from app.engine.runtime import _REL_EVENTS


def test_new_scores_carry_trust():
    s = rel.new_scores()
    assert s["trust"] == rel.START_TRUST


def test_trust_slow_build_quick_break():
    s = rel.new_scores()
    up = rel.apply_deltas(s, 0, 0, None, trust_delta=6)
    assert up["trust"] > s["trust"]
    dn = rel.apply_deltas(up, 0, 0, None, trust_delta=-8)
    # 跌幅全额, 涨幅有 taper — 一涨一跌净值必须为负 (慢建快塌)
    assert dn["trust"] < s["trust"] or dn["trust"] < up["trust"] - 6 + 1
    # 单回合步幅钳制先于范围钳制 (渐变家法): 一拍最多塌 TRUST_STEP[0]
    assert rel.apply_deltas(s, 0, 0, None, trust_delta=-999)["trust"] \
        == max(rel.TRUST_MIN, rel.START_TRUST + rel.TRUST_STEP[0])
    ground = s
    for _ in range(6):   # 连塌几拍才能见底
        ground = rel.apply_deltas(ground, 0, 0, None, trust_delta=-999)
    assert ground["trust"] == rel.TRUST_MIN


def test_old_scores_without_trust_default_in():
    legacy = {"closeness": 50, "romance": 20}   # 存量档没有 trust 键
    out = rel.apply_deltas(legacy, 1, 0, None)
    assert out["trust"] == rel.START_TRUST
    assert rel.trust_note(legacy) != ""          # 低信任高亲近 → 戒备档


def test_trust_note_bands_zh_en():
    guarded_close = {"closeness": 60, "romance": 0, "trust": 10}
    n = rel.trust_note(guarded_close)
    assert "戒备" in n and "交底" in n            # 嘴上热心里防那一档
    n_en = rel.trust_note(guarded_close, lang="en")
    assert "Guarded" in n_en and not any("一" <= ch <= "鿿" for ch in n_en)
    assert "信任" in rel.trust_note({"closeness": 5, "romance": 0, "trust": 80})
    assert rel.trust_note({"closeness": 5, "romance": 0, "trust": 40}) == ""   # 常态无声


def test_rel_events_are_five_tuples_with_trust():
    for kind, law in _REL_EVENTS.items():
        assert len(law) == 5, kind
    assert _REL_EVENTS["交心"][4] > 0 and _REL_EVENTS["越界"][4] < 0
