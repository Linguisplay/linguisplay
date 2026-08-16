# -*- coding: utf-8 -*-
"""🏖 沙盒九键形状闸: linter 对 sandbox 内容零校验 (logic.py 只查它和其他系统的
冲突警告), 形状错 = 修为/串门/出生点静默失效。问卷起草管线必须自己把这道关。
原则: 确定性修剪, 不报错不打断 (烂零件摘掉, 世界照样能开)。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_sanitize.db")
os.environ.setdefault("JWT_SECRET", "test")

from app.engine.logic import sanitize_sandbox  # noqa: E402


def _story(sandbox):
    return {"characters": [{"id": "ch_1", "name": "甲"}],
            "locations": [{"id": "loc_1", "name": "山门"}],
            "sandbox": sandbox}


def test_a_broken_progression_is_removed_not_kept():
    s = _story({"enabled": True, "progression": {"name": "", "ranks": ["a"]}})
    notes = sanitize_sandbox(s)
    assert "progression" not in s["sandbox"], "坏阶梯留着 = 修为系统静默失效"
    assert notes


def test_a_good_progression_survives_intact():
    ranks = ["淬体", "凝气", "问剑", "御剑", "剑心通明", "化神"]
    s = _story({"enabled": True, "progression": {"name": "剑心", "ranks": ranks}})
    sanitize_sandbox(s)
    assert s["sandbox"]["progression"] == {"name": "剑心", "ranks": ranks}


def test_dangling_visitor_and_start_location_are_pruned():
    s = _story({"enabled": True, "opening_visitor": "ch_99", "start_location": "loc_99"})
    sanitize_sandbox(s)
    assert "opening_visitor" not in s["sandbox"]
    assert "start_location" not in s["sandbox"]


def test_valid_visitor_and_start_location_survive():
    s = _story({"enabled": True, "opening_visitor": "ch_1", "start_location": "loc_1"})
    assert sanitize_sandbox(s) == []
    assert s["sandbox"]["opening_visitor"] == "ch_1"


def test_powers_are_clamped_to_four_and_forty_chars():
    s = _story({"enabled": True, "default_powers": ["长" * 60, "b", "c", "d", "e"]})
    sanitize_sandbox(s)
    ps = s["sandbox"]["default_powers"]
    assert len(ps) == 4 and all(len(p) <= 40 for p in ps), \
        "开档层还会截一刀 (runs.py:676) — 不在这里压好, 超出的字就静默蒸发"


def test_bogus_start_money_falls_back():
    s = _story({"enabled": True, "start_money": "很多"})
    sanitize_sandbox(s)
    assert s["sandbox"]["start_money"] == 100


def test_non_dict_sandbox_is_left_alone():
    s = {"characters": [], "locations": [], "sandbox": "corrupt"}
    assert sanitize_sandbox(s) == []
    assert s["sandbox"] == "corrupt"   # 老档实弹出现过字符串, 引擎自己会容错


def test_non_dict_members_in_cast_or_locations_do_not_crash():
    s = {"characters": ["corrupt", None, {"id": "ch_1"}],
         "locations": [None, {"id": "loc_1"}],
         "sandbox": {"enabled": True, "opening_visitor": "ch_1",
                     "start_location": "loc_1"}}
    sanitize_sandbox(s)   # 不许抛
    assert s["sandbox"]["opening_visitor"] == "ch_1"
