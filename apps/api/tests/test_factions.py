# -*- coding: utf-8 -*-
"""🏛 阵营声望账本 (Yi 2026-07-22: 引擎要承担更多故事类型 — 权谋/宫斗/帮派地基):
发言者代表阵营报审 rep_delta, 引擎钳制入账, 对头反向记半; 档位以提示块注入底色;
角色指向不存在的阵营被 lint 拦下。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from app.engine import factions, logic, runtime  # noqa: E402

STORY = {"story": {
    "id": "s",
    "characters": [
        {"id": "a", "name": "东厂番子", "is_lead": True, "faction_id": "east"},
        {"id": "b", "name": "布衣客", "home_location_id": "hall"}],
    "acts": [{"index": 1, "title": "一"}],
    "locations": [{"id": "hall", "name": "门厅", "detail": "x", "exits": []}],
    "factions": [
        {"id": "east", "name": "东厂", "detail": "只认势不认理", "rivals": ["jin"]},
        {"id": "jin", "name": "锦衣卫", "rivals": ["east"]}]},
    "secrets": []}


def test_ledger_clamp_and_rival_ripple():
    st = {}
    applied = factions.apply_delta(st, STORY, "east", 5)      # 报5 → 钳到+3, 对头-1
    assert applied == {"east": 3, "jin": -1}
    assert st["reputation"] == {"east": 3, "jin": -1}
    factions.apply_delta(st, STORY, "east", -5)               # 反向同理
    assert st["reputation"]["east"] == 0 and st["reputation"]["jin"] == 0
    assert factions.apply_delta(st, STORY, "nobody", 3) == {}  # 野阵营不入账
    assert factions.band(60) == "器重" and factions.band(0) == "中立"
    assert factions.band(-60) == "仇视"


def test_block_gating_and_view():
    st = {"reputation": {"east": 30, "jin": -26}}
    blk = factions.block(STORY, st, STORY["story"]["characters"][0])
    assert "东厂" in blk and "接纳" in blk
    assert "锦衣卫" in blk and "有怨言" in blk        # 对头传闻 (|rep|≥25 才有耳闻)
    assert factions.block(STORY, st, STORY["story"]["characters"][1]) == ""  # 无阵营无块
    v = factions.view(STORY, st)
    assert [x["id"] for x in v] == ["east", "jin"]   # 按名声绝对值排序


def test_turn_reports_and_books_reputation():
    class CourtLLM:
        def generate(self, prompt):
            if prompt.get("speaker_name") == "东厂番子" or prompt.get("speaker"):
                # 发言者带阵营 → schema 有 faction_rep 字段; 报审走 rep_delta
                return {"beats": [{"type": "dialogue", "speaker_name": "东厂番子",
                                   "text": "算你识相。"}],
                        "rep_delta": 9,   # 越界报审 → 引擎钳到 +3 (真路径由 faction_rep 映射而来)
                        "affinity_delta": 0, "advance_act": False, "ending": None}
            return {"beats": [], "affinity_delta": 0, "advance_act": False, "ending": None}

    out = runtime.run_turn(STORY, runtime.default_state(), {"name": "我"},
                           "这份名册，我给你们东厂送来了", channel="say", llm=CourtLLM())
    assert out["state"]["reputation"]["east"] == 3
    assert out["state"]["reputation"]["jin"] == -1
    assert out["factions"] and out["factions"][0]["name"] == "东厂"


def test_lint_catches_dangling_faction():
    bad = {"story": {**STORY["story"],
                     "characters": [{"id": "a", "name": "甲", "is_lead": True,
                                     "faction_id": "ghost_gang"}]},
           "secrets": []}
    codes = {i["code"] for i in logic.lint_story(bad)}
    assert "bad_faction" in codes
    assert "bad_faction" not in {i["code"] for i in logic.lint_story(STORY)}
