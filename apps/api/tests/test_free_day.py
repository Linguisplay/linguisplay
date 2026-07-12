# -*- coding: utf-8 -*-
"""🌅 每天的自由活动时段 (Yi): 菜单从作息+关系温度长出来, 确定性."""
from app.engine import relationships, runtime

STORY = {
    "story": {"id": "s", "tuning": {"turns_per_slot": 1},
              "characters": [
                  {"id": "a", "name": "甲", "is_lead": True, "home_location_id": "hall"},
                  {"id": "b", "name": "乙", "home_location_id": "alley"},
                  {"id": "c", "name": "丙", "home_location_id": "hall"}],
              "acts": [{"index": 1, "title": "一"}],
              "locations": [
                  {"id": "hall", "name": "门厅", "detail": "x", "exits": ["后巷"]},
                  {"id": "alley", "name": "后巷", "detail": "y", "exits": ["门厅"]}]},
    "secrets": [],
}


def _warm(st, cid, closeness):
    sc = relationships.new_scores()
    sc["closeness"] = closeness
    st.setdefault("rel", {})[cid] = sc


def test_menu_leads_with_warmest_and_names_places():
    st = runtime.default_state()
    st["met_ids"] = ["a", "b", "c"]
    st["location_id"] = "hall"
    _warm(st, "b", 70)
    _warm(st, "a", 30)
    menu = runtime.free_day_suggestions(STORY, st)
    assert menu and len(menu) <= 3
    assert "乙" in menu[0], "最暖的人排第一"
    assert any(("门厅" in m or "后巷" in m) for m in menu), "去处要落到真实地点"


def test_menu_skips_dead_and_offers_solo():
    st = runtime.default_state()
    st["met_ids"] = ["a", "b"]
    st["location_id"] = "hall"
    st["dead_character_ids"] = ["b"]
    _warm(st, "b", 90)
    menu = runtime.free_day_suggestions(STORY, st)
    assert all("乙" not in m for m in menu), "死者不进菜单"
    assert any("一个人" in m for m in menu), "永远有独处选项"


def test_menu_empty_world_degrades():
    st = runtime.default_state()
    assert isinstance(runtime.free_day_suggestions(STORY, st), list)
