# -*- coding: utf-8 -*-
"""🎭 IP 经典形象 (Yi 2026-07-28: 同人角色生图要画成大家认得的那张脸)。"""
from app.engine import ipface


def test_ip_detected_from_fan_tags():
    st = {"trope_tags": ["斗罗大陆", "同人致敬", "玄幻", "沙盒"]}
    assert ipface.ip_of(st) == "斗罗大陆"
    st2 = {"trope_tags": ["全职法师", "同人致敬", "都市异能"]}
    assert ipface.ip_of(st2) == "全职法师"


def test_marker_first_falls_through():
    """同人标记排在第一位时, 往后取真正的 IP 名。"""
    assert ipface.ip_of({"trope_tags": ["同人致敬", "斗罗大陆", "玄幻"]}) == "斗罗大陆"


def test_original_story_has_no_ip():
    """原创本不加经典形象条款 —— 否则画图模型会去凑一个不存在的"原作"。"""
    assert ipface.ip_of({"trope_tags": ["黑帮", "城寨", "卧底", "年代"]}) == ""
    assert ipface.ip_of({"trope_tags": []}) == ""
    assert ipface.ip_of({}) == ""


def test_canon_clause_shape():
    c = ipface.canon_clause("斗罗大陆", "唐三")
    assert "《斗罗大陆》" in c and "唐三" in c and "经典形象" in c
    assert "发色" in c and "一眼认得出" in c
    assert ipface.canon_clause("", "唐三") == ""
    assert ipface.canon_clause("斗罗大陆", "") == ""


def test_looks_pulled_from_web_knowledge():
    """联网检索产出里的外貌要点要接到画笔上 (它以前只进 knowledge 字段)。"""
    kn = ("【人物设定】唐三，蓝银草与昊天锤双生武魂的少年。外貌上是黑发黑眸，"
          "常穿一身朴素的蓝色劲装。口癖沉稳。\n【世界背景】斗罗大陆分三大帝国。")
    got = ipface.looks_from_knowledge(kn)
    assert "黑发黑眸" in got and "蓝色劲装" in got
    assert "三大帝国" not in got          # 只取人物设定段
    assert ipface.looks_from_knowledge("") == ""


def test_canon_clause_merges_knowledge_looks():
    kn = "【人物设定】外貌是一头银白长发，瞳色偏紫。"
    c = ipface.canon_clause("某作", "某人", kn)
    assert "外貌要点" in c and "银白长发" in c
