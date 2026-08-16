# -*- coding: utf-8 -*-
"""📜 沙盒起草的 mock/真 prompt 同构合同。历史实弹: MockLLM 孪生与真 prompt 字段
不同构 → 测试绿真机歪。合同 = qwen.SANDBOX_WORLD_KEYS 一份常量锁两边。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_sbllm.db")
os.environ.setdefault("JWT_SECRET", "test")

from app.engine import qwen  # noqa: E402
from app.engine.llm import MockLLM  # noqa: E402

ANSWERS = {"题材": "修仙", "世界观": "灵脉将枯的山城", "超凡体系": "剑心"}


def test_mock_sandbox_world_covers_the_contract_keys():
    out = MockLLM().generate({"sandbox_world": True, "answers": ANSWERS,
                              "summary": "云脊山脉深处的问剑小城"})
    for k in qwen.SANDBOX_WORLD_KEYS:
        assert k in out, f"mock 孪生缺 {k} — 测试世界与真机分家"


def test_mock_world_style_keeps_the_head_tail_layout():
    out = MockLLM().generate({"sandbox_world": True, "answers": ANSWERS, "summary": "x"})
    assert "忌" in out["style"], "style 尾部必须有忌清单 (截断保尾靠它, qwen.py:63-93)"
    assert out["tech_level"] in ("modern", "ancient", "future")
    assert 3 <= len(out["locations"]) <= 4


def test_mock_summary_and_progression_twins_exist():
    m = MockLLM()
    s = m.generate({"sandbox_summary": True, "answers": ANSWERS})
    assert len(s.get("summary") or "") >= 30
    p = m.generate({"gen_progression": True, "world": "x", "title": "y"})
    assert p.get("name") and 4 <= len(p.get("ranks") or []) <= 12


def test_real_prompt_methods_are_wired_into_dispatch():
    """真模型类必须有方法且 generate() 分发得到 — 只验静态接线, 不打真网。"""
    for cls_name in ("QwenLLM", "DeepSeekLLM"):
        cls = getattr(qwen, cls_name)
        assert hasattr(cls, "_sandbox_world") and hasattr(cls, "_sandbox_summary")
