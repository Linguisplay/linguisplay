# -*- coding: utf-8 -*-
"""🪞 玩家档案 (活世界 P2): 蒸馏节拍、认知边界、增量合并."""
from app.engine import profile
from app.engine.llm import MockLLM


def test_note_turn_cadence():
    """⚠️ 节拍 2026-08-08 改成「头一次早、之后稀疏」：从前是每 8 拍一次，而一局的
    玩家回合数中位只有 4 —— 一半以上的玩家在档案第一次运行之前就走了。
    详见 test_profile_lands_early.py。"""
    st = {}
    hits = [profile.note_turn(st) for _ in range(profile.DISTILL_FIRST + profile.DISTILL_EVERY)]
    assert hits[profile.DISTILL_FIRST - 1] is True, "第一次没落在 DISTILL_FIRST 上"
    assert hits.count(True) == 2, "这一段里应该正好蒸两次（首次 + 一个间隔）"


def test_distill_merges_facts_and_impressions():
    st = {"clock": {"day": 3}}
    ok = profile.distill({}, st, ["玩家：我先看看再动手"],
                         [{"id": "c1", "name": "阿箬"}], MockLLM())
    assert ok
    assert profile.facts_of(st)
    assert profile.impression_of(st, "c1")
    assert st["profile"]["by_char"]["c1"]["day"] == 3


def test_witness_boundary_blocks_absent_characters():
    """模型越权给不在场的角色写印象 → 引擎丢弃."""
    st = {}

    class Leaky:
        def generate(self, prompt):
            return {"facts": ["爱冒险"],
                    "impressions": {"c1": "在场的印象", "ghost": "偷来的印象"}}

    profile.distill({}, st, ["……"], [{"id": "c1", "name": "阿箬"}], Leaky())
    assert profile.impression_of(st, "c1") == "在场的印象"
    assert profile.impression_of(st, "ghost") == ""


def test_distill_failure_is_silent():
    class Boom:
        def generate(self, prompt):
            raise RuntimeError("network")

    st = {}
    assert profile.distill({}, st, ["……"], [{"id": "c1", "name": "阿箬"}], Boom()) is False
    assert profile.facts_of(st) == []


def test_empty_impression_for_unknown():
    assert profile.impression_of({}, "nobody") == ""
    assert profile.impression_of({}, None) == ""
