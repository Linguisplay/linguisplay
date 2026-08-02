# -*- coding: utf-8 -*-
"""🎵 配乐的四条底线。

  ① 每一格情绪都得响出【真曲】—— 曲库里那批 24 秒的老合成器片循环一整局很难听,
     没有真曲的情绪必须有 fallback 指到情绪最近的真曲上。
  ② 作者在剧本里按情绪点了名, 就压过引擎的一切默认与轮换 —— 点名就是点名。
  ③ 硬状态仍归引擎: 床笫的浪漫曲、危机的紧张曲不容作者也不容乐师改判。
  ④ 工坊下拉菜单里只许出现【文件真的在】的曲子, 不许列出点了没声的。
"""
import os
import re

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_bgm.db")
os.environ.setdefault("JWT_SECRET", "test")

import pytest  # noqa: E402

from app.engine import director  # noqa: E402

# ⚠️ 真曲库 gal_*.mp3 只活在服务器上 (art 不进 git, 本地 checkout 只有那批 24 秒的裸文件),
# 所以"文件在不在"这类断言本地跳过、部署时在服务器上跑; 纯逻辑的那些永远跑。
REAL = {p.stem for p in director.bgm_dir().glob("gal_*.mp3")}
has_lib = pytest.mark.skipif(not REAL, reason="本机没有 gal_* 真曲库 (它只在服务器上)")


def _content(bgm=None):
    return {"story": {"id": "s", "tuning": ({"bgm": bgm} if bgm else {})}}


# ── ① 每格情绪都有真曲可响 ────────────────────────────────────────────────
def test_no_mood_resolves_into_a_slot_we_know_is_empty():
    """纯逻辑版 (不看文件): 声明了 fallback 就等于承认这一格没有真曲 ——
    那么谁也不许把默认曲解析到这样一格上, fallback 自己也不许指向另一个空格。"""
    empty = {k for k, v in director.BGM_TRACKS.items() if v.get("fallback")}
    for key in director.BGM_TRACKS:
        got = re.sub(r"\d+$", "", director.resolve_bgm(None, key, "salt"))
        got = got[4:] if got.startswith("gal_") else got
        assert got not in empty, f"{key} 的默认曲解析到了空格 {got}"


@has_lib
def test_every_mood_lands_on_a_real_track():
    missing = []
    for key in director.BGM_TRACKS:
        got = director.resolve_bgm(None, key, "salt")
        stem = f"gal_{got}" if not got.startswith("gal_") else got
        if stem not in REAL and re.sub(r"\d+$", "", stem) not in REAL:
            missing.append(f"{key} → {got}")
    assert not missing, (
        "这些情绪落不到真曲上, 玩家会听 24 秒的老合成器片循环一整局: " + "、".join(missing))


def test_the_two_empty_slots_declare_a_fallback():
    for key in ("ancient", "grimdark"):
        assert director.BGM_TRACKS[key].get("fallback"), f"{key} 没有真曲又没写 fallback"
        assert director.default_track(key) != f"gal_{key}"


# ── ② 作者点名压过一切 ────────────────────────────────────────────────────
def test_author_pick_beats_the_default_library():
    assert director.resolve_bgm(_content({"ancient": "gal_mystery2"}),
                                "ancient", "x") == "gal_mystery2"


def test_author_pick_is_not_rotated_into_a_variant():
    """点名就是点名 —— 换地方换天也不许给他轮成 gal_daily3。"""
    c = _content({"daily": "gal_daily"})
    picks = {director.resolve_bgm(c, "daily", f"loc{i}|{i}") for i in range(12)}
    assert picks == {"gal_daily"}


def test_no_pick_still_rotates_variants():
    picks = {director.resolve_bgm(None, "daily", f"loc{i}|{i}") for i in range(30)}
    assert len(picks) > 1, "没点名时该按地点/日子轮换变奏, 免得整局一首"


def test_an_unknown_or_empty_pick_falls_back_instead_of_going_silent():
    for junk in ({}, {"daily": ""}, {"daily": "   "}, {"other": "gal_warm"}):
        got = director.resolve_bgm(_content(junk), "daily", "x")
        assert got and got.startswith("daily") or got.startswith("gal_"), got


# ── ③ 硬状态不容改判 ──────────────────────────────────────────────────────
def test_engine_still_owns_the_hard_states():
    assert director.pick_bgm("daily", heat=2) == "romantic"      # 床笫
    assert director.pick_bgm("daily", hot=True) == "tense"       # 危机
    assert director.pick_bgm("battle", hot=True) == "battle"     # 但不夺高能量曲的戏


def test_stage_turn_threads_the_authors_choice_through():
    final = {"scene": {"mood": "ancient"}, "state": {"location_id": "L", "clock": {"day": 1}}}
    assert director.stage_turn(final)["bgm"] != "ancient"        # 默认走 fallback
    out = director.stage_turn(final, _content({"ancient": "gal_sad"}))
    assert out["bgm"] == "gal_sad"
    assert out["mood"] == "ancient", "判到的情绪要一起下发, 作者才调得动"


def test_stage_turn_survives_a_junk_story():
    for c in (None, {}, {"story": None}, {"story": {"tuning": None}},
              {"story": {"tuning": {"bgm": "不是字典"}}}):
        assert director.stage_turn({"scene": {"mood": "daily"}, "state": {}}, c)["bgm"]


# ── ④ 菜单只列真的存在的曲子 ──────────────────────────────────────────────
def test_the_studio_menu_only_offers_files_that_exist():
    tracks = director.list_bgm()
    assert tracks, "曲库一首都列不出来 — 工坊的下拉会是空的"
    for t in tracks:
        assert (director.bgm_dir() / f"{t['file']}.mp3").exists(), t


@has_lib
def test_the_menu_marks_which_ones_are_real_music():
    assert any(t["real"] for t in director.list_bgm())


def test_every_mood_shows_up_in_the_menu_with_a_human_name():
    menu = director.mood_menu()
    assert {m["key"] for m in menu} == set(director.BGM_TRACKS)
    for m in menu:
        assert m["label"] and m["label"] != m["key"], f"{m['key']} 没有人话名字"
        assert m["default"]
