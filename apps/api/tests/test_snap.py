# -*- coding: utf-8 -*-
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
