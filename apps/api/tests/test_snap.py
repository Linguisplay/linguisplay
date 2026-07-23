# -*- coding: utf-8 -*-
# 📷 同脸铁律 (2026-07-15): 自拍包必须带身份锚 — 见文末 test_selfie_carries_identity_anchor
"""📷 随手拍: a character's text can occasionally carry a photo — engine rolls the
dice and owns the per-thread cooldown; calls never carry one; mock/no-key mode
never mints an unrenderable URL."""
from types import SimpleNamespace

from app.engine import runtime

SB = {"story": {"id": "sn", "sandbox": {"enabled": True},
                "characters": [{"id": "c1", "name": "Mara", "persona_text": "短发女人"}],
                "acts": [{"index": 1}],
                "locations": [{"id": "l1", "name": "天台", "detail": "夜里的天台", "exits": []}]},
      "secrets": []}


def _on(monkeypatch, roll=1):
    monkeypatch.setattr(runtime, "get_settings",
                        lambda: SimpleNamespace(llm_provider="qwen", dashscope_api_key="k"))
    monkeypatch.setattr(runtime._rng, "randint", lambda a, b: roll)


def test_snap_attaches_to_last_bubble_and_cools_down(monkeypatch):
    _on(monkeypatch, roll=1)   # passes the chance roll, picks the selfie flavor
    st = runtime.default_state()
    c = SB["story"]["characters"][0]
    ev = runtime.phone_push(SB, st, c, ["看这个", "刚拍的"], "夜")
    assert ev["snap"] and ev["snap"]["url"].startswith("/scene/snap/")
    assert ev["snap"]["prompt"]
    th = st["phone"]["threads"]["c1"]
    assert th["msgs"][-1]["img"] == ev["snap"]["url"]     # last bubble carries it
    assert "img" not in th["msgs"][0]
    ev2 = runtime.phone_push(SB, st, c, ["再看"], "夜")   # gap cooldown holds
    assert ev2["snap"] is None


def test_snap_off_in_mock_mode_or_zero_chance(monkeypatch):
    monkeypatch.setattr(runtime, "get_settings",
                        lambda: SimpleNamespace(llm_provider="mock", dashscope_api_key="k"))
    st = runtime.default_state()
    assert runtime.maybe_snap(SB, st, SB["story"]["characters"][0], "x") is None
    _on(monkeypatch, roll=1)
    off = {"story": {**SB["story"], "tuning": {"snap_chance": 0}}, "secrets": []}
    assert runtime.maybe_snap(off, runtime.default_state(),
                              SB["story"]["characters"][0], "x") is None


def test_calls_never_carry_photos(monkeypatch):
    _on(monkeypatch, roll=1)
    st = runtime.default_state()
    ev = runtime.phone_push(SB, st, SB["story"]["characters"][0], ["喂"], "夜", call=True)
    assert ev.get("snap") is None


def test_art_style_rides_the_snap_prompt(monkeypatch):
    _on(monkeypatch, roll=50)   # >45 → 随手拍 flavor, still passes 12-chance? 50>12 fails…
    monkeypatch.setattr(runtime._rng, "randint", lambda a, b: 10)  # pass chance, 拍景 flavor? 10<=45 selfie
    styled = {"story": {**SB["story"],
                        "tuning": {"art_style": "阴郁冷调恐怖片美术"}}, "secrets": []}
    assert runtime.art_style_of(styled) == "阴郁冷调恐怖片美术"
    assert runtime.art_style_of(SB) == ""
    sn = runtime.maybe_snap(styled, runtime.default_state(),
                            SB["story"]["characters"][0], "看")
    assert sn and "阴郁冷调恐怖片美术" in sn["prompt"]


def test_selfie_carries_identity_anchor(monkeypatch):
    """📷 同脸铁律 (Yi 2026-07-15): 自拍包必须带身份锚 — cid + char_seed + 场景,
    router 才能走 i2i 保脸或定种 t2i; 风景拍不带 (没有脸要保)。"""
    _on(monkeypatch, roll=1)   # roll=1 → 过概率关 + 选自拍口味
    st = runtime.default_state()
    st["phone"] = {"threads": {"c1": {"msgs": [], "unread": 0, "snap_since": 99}}}
    c = SB["story"]["characters"][0]
    sn = runtime.maybe_snap(SB, st, c, "在吗")
    assert sn and sn.get("selfie") is True and sn.get("cid") == "c1"
    assert isinstance(sn.get("seed"), int)          # char_seed: 历张自拍互相同脸
    assert "自拍" in sn["prompt"] and sn.get("scene")
    # 风景口味: 两次掷骰同参 (1,100), 只能按次序造假 — 第一掷过概率关, 第二掷 50>45 选风景
    st["phone"]["threads"]["c1"]["snap_since"] = 99
    _rolls = iter([1, 50])
    monkeypatch.setattr(runtime._rng, "randint", lambda a, b: next(_rolls))
    sn2 = runtime.maybe_snap(SB, st, c, "在吗")
    assert sn2 and not sn2.get("selfie") and "眼前的景象" in sn2["prompt"]
