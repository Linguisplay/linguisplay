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


def test_variants_come_from_the_disk_not_from_a_hand_written_count():
    """手写的 variants 数字与磁盘对不上时, 玩家听到的就是 24 秒片 (实弹: eerie 写 2, 只有 gal_eerie2)。
    所以轮换只许在【文件真的在】的曲子之间进行。"""
    for key in director.BGM_TRACKS:
        got = director.real_variants(key)
        for stem in got:
            assert (director.bgm_dir() / f"{stem}.mp3").exists(), stem
        if got:
            picks = {director.pick_variant(key, f"L{i}|{i}") for i in range(40)}
            assert picks <= set(got), f"{key} 轮到了不存在的曲子: {picks - set(got)}"


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


@has_lib
def test_the_empty_slots_actually_play_something_else():
    for key in ("ancient", "grimdark"):
        assert not director.real_variants(key), f"{key} 居然有真曲了 — fallback 可以撤了"
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


# ── ②b 剧情节拍: 故事走到哪一步 ────────────────────────────────────────────
def _final(**kw):
    f = {"scene": {}, "state": {"turn_seq": 9}}
    f.update(kw)
    return f


def test_the_story_beats_are_read_off_state_the_engine_already_keeps():
    """节拍不新增字段、不问模型 —— 全部从引擎已经在算的东西里认。"""
    assert director.cue_of(_final(ending={"id": "e1"})) == "finale"
    assert director.cue_of(_final(pending_choice={"prompt": "?"})) == "climax"
    assert director.cue_of(_final(state={"heat": {"stage": 2}, "turn_seq": 9})) == "intimate"
    assert director.cue_of(_final(threat_view={"alert": True})) == "crisis"
    assert director.cue_of(_final(pressure_view={"value": 80})) == "crisis"
    assert director.cue_of(_final(state={"heat": {"stage": 1}, "turn_seq": 9})) == "flirt"
    assert director.cue_of(_final(rel_deltas={"a": 3})) == "flirt"
    assert director.cue_of(_final(scene={"mood": "romantic"})) == "flirt"
    assert director.cue_of(_final(state={"turn_seq": 0})) == "opening"
    assert director.cue_of(_final()) == "daily"


def test_the_ending_beat_is_never_stolen_by_the_crisis_beat():
    """结局那一拍常常同时压力拉满 —— 落幕必须压过危机, 不然谢幕在放追逐曲。"""
    assert director.cue_of(_final(ending={"id": "e"}, threat_view={"alert": True},
                                  pressure_view={"value": 99})) == "finale"
    assert director.cue_of(_final(pending_choice={"p": 1},
                                  pressure_view={"value": 99})) == "climax"


def test_a_fresh_run_opens_with_the_opening_beat_not_silence():
    """以前 direct 只在回合流里发, 新档第一屏是静的。现在进档就判得出节拍。"""
    out = director.stage_turn({"scene": {}, "state": {"turn_seq": 0}}, None)
    assert out["cue"] == "opening" and out["bgm"]


def test_author_can_score_a_beat_and_it_beats_the_scene_mood():
    c = _content({"opening": "gal_warm2", "eerie": "gal_mystery"})
    final = {"scene": {"mood": "eerie"}, "state": {"turn_seq": 0}}
    assert director.stage_turn(final, c)["bgm"] == "gal_warm2", "节拍要压过气氛"
    later = {"scene": {"mood": "eerie"}, "state": {"turn_seq": 9}}
    assert director.stage_turn(later, c)["bgm"] == "gal_mystery", "不在节拍上时才轮到气氛"


def test_a_beat_alone_never_changes_the_engines_own_pick():
    """节拍不带默认覆盖 —— 作者没点名时, 选曲跟没有这一层时一模一样。
    第一版让节拍自带气氛压过引擎, 当场压坏了「危机不夺战斗曲的戏」那条既有规则。"""
    for final in ({"scene": {"mood": "battle"}, "state": {"turn_seq": 0},
                   "threat_view": {"alert": True}},
                  {"scene": {"mood": "lonely"}, "state": {"turn_seq": 0}},
                  {"scene": {"mood": "eerie"}, "state": {"heat": {"stage": 1}}}):
        st = final["state"]
        salt = f"{st.get('location_id') or ''}|{(st.get('clock') or {}).get('day', 0)}"
        want = director.resolve_bgm(None, director.pick_bgm(
            final["scene"]["mood"],
            pressure=0, hot=bool((final.get("threat_view") or {}).get("alert")),
            heat=int((st.get("heat") or {}).get("stage") or 0)), salt)
        assert director.stage_turn(final, None)["bgm"] == want


def test_every_beat_has_a_human_name_and_a_default():
    for c in director.cue_menu():
        assert c["label"] and c["when"] and c["default"], c
    assert [c["key"] for c in director.cue_menu()][0] == "finale", "顺序即优先级"


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
