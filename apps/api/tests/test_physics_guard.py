# -*- coding: utf-8 -*-
"""🧊 物理连续性哨兵 (Yi: 道具/伤势穿模——裤兜掏瓶装汽水/断肋骨扛货):
预筛(只在动作字眼时跑)+ flash 探硬矛盾 → 接进 _logic_guard 当场重生。"""
from app.engine import runtime


class _FakeLLM:
    """带 _url 假装真 LLM; breaks 脚本化 flash 审校返回。"""
    _url, _key, _model = "http://x", "k", "deepseek-v4-pro"

    def __init__(self, breaks):
        self.breaks = breaks
        self.calls = 0


def test_prefilter_skips_pure_dialogue(monkeypatch):
    """纯聊天(无动作字眼)→ 不跑 flash, 零延迟。"""
    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        raise AssertionError("不该调用 flash")

    monkeypatch.setattr("app.engine.qwen._post_chat", _boom)
    directed = {"beats": [{"type": "dialogue", "speaker_name": "甲", "text": "你今天真好看，我很开心。"}]}
    assert runtime._physics_audit(_FakeLLM([]), directed, {}) == []
    assert called["n"] == 0


def test_action_turn_runs_flash_and_flags(monkeypatch):
    """有动作字眼(掏/汽水)→ 跑 flash; 探到穿模就返回。"""
    class _Resp:
        def json(self):
            return {"choices": [{"message": {"content": '{"breaks":["裤兜掏出整瓶玻璃汽水"]}'}}]}

    monkeypatch.setattr("app.engine.qwen._post_chat", lambda *a, **k: _Resp())
    directed = {"beats": [{"type": "description", "text": "他从裤兜里掏出一罐冰镇汽水。"}]}
    out = runtime._physics_audit(_FakeLLM([]), directed, {})
    assert out == ["裤兜掏出整瓶玻璃汽水"]


def test_mock_llm_no_url_skips():
    """MockLLM(无 _url) → 跳过, 不阻断。"""
    directed = {"beats": [{"type": "description", "text": "他掏出一把刀。"}]}
    assert runtime._physics_audit(object(), directed, {}) == []


def test_flash_failure_degrades_to_empty(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("flash 挂了")

    monkeypatch.setattr("app.engine.qwen._post_chat", _boom)
    directed = {"beats": [{"type": "description", "text": "他掏出一把刀。"}]}
    assert runtime._physics_audit(_FakeLLM([]), directed, {}) == []   # 绝不抛


def test_tuning_default_on():
    assert runtime.DEFAULT_TUNING.get("physics_guard") == 1
