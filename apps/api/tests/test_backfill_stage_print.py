# -*- coding: utf-8 -*-
"""🎬 存量补表演指纹工具 (backfill_stage_print.py): 引擎起草三维, 提案验收后 --apply。
只补空维、名一致才填、重名弃、id缺跳——和 voice_print 补票同套安全网。"""
import backfill_stage_print as bsp
from app.engine.llm import MockLLM


class _S:
    title, language, world_long, style = "T", "zh", "黑帮世界", ""


def test_draft_maps_and_distinct():
    chars = [{"id": "a", "name": "龙卷风", "persona_text": "沉稳话事人"},
             {"id": "b", "name": "十二少", "persona_text": "冲动头马"}]
    prints = bsp._draft(MockLLM(), _S(), chars)
    assert [p["id"] for p in prints] == ["a", "b"]
    # 三维都出了, 且两人不全撞
    assert all(p.get("act_pace") and p.get("sense_focus") and p.get("emote_form") for p in prints)
    assert prints[0]["act_pace"] != prints[1]["act_pace"]


def test_draft_drops_dup_names():
    prints = bsp._draft(MockLLM(), _S(), [{"id": "a", "name": "王九"}, {"id": "b", "name": "王九"}])
    assert all(p["name"] != "王九" for p in prints)


def test_fill_only_empty_dims_name_checked():
    chars = [{"id": "a", "name": "龙卷风", "act_pace": "作者手写", "sense_focus": "", "emote_form": ""}]
    n = bsp._fill(chars, {"a": {"act_pace": "X", "sense_focus": "视觉主导",
                                "emote_form": "只做事不表达", "name": "龙卷风"}})
    assert n == 1
    assert chars[0]["act_pace"] == "作者手写"          # 已填的不覆盖
    assert chars[0]["sense_focus"] == "视觉主导"        # 空维补上


def test_fill_skips_renamed():
    chars = [{"id": "a", "name": "沈青梧", "act_pace": "", "sense_focus": "", "emote_form": ""}]
    n = bsp._fill(chars, {"a": {"act_pace": "利落", "name": "龙卷风"}})
    assert n == 0 and not chars[0]["act_pace"]


def test_needs_print_gate():
    assert bsp._needs_print({"name": "甲"})                                  # 全空 = 需要
    assert not bsp._needs_print({"name": "乙", "act_pace": "利落"})          # 有一维 = 不算缺
    assert not bsp._needs_print({"act_pace": ""})                            # 无名 = 跳
