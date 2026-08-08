# -*- coding: utf-8 -*-
"""🧍 姿位账本不许自己跟自己打架 (线上实弹 2026-08-08)。

存档 ca3f993b 的审计单上并排躺着这两条:

    pos.set   你:跟在千夏身后往海堤走
    (而 state["player_pos"]["at"] == 商店街的 id, location_id 一动没动)

一条记录里, 文说在往【海堤】走, 实说人在【商店街】。这不是「文与实分家」——
这是文与实【长在同一行】上打架。姿位是模型填的自由文本, 引擎原样收下, 一个字都没验。

后果比读着别扭严重: 姿位会回喂给下一拍当锚。于是模型下一拍看到自己写的「往海堤走」,
理所当然接着往海堤演, 位置永远追不上 —— 一次幻觉自己给自己续了命。

修法只做一件事: 姿位文本里点到【别的在册地点】就不收这一条 (原地走动照收)。
拦下来的那次要留痕 —— 不留痕就永远量不出它发生过多少回。

【为什么读口选姿位而不选散文】线上全量实测:
  · 姿位字段: 287 条里 2 条点了别处, 两条都是真的 (0.7% 报警率)
  · 散文按地点别名扫: 32 条候选, 人工过一遍绝大多数是误报 —— 剧本的地点名成串地
    共享前缀 (「X·前厅」「X·后院」) 或含通用词, 别名一放宽就互相撞。
所以这个读口钉在姿位这个【短的、结构化的】字段上, 不去猜散文。
"""
from app.engine import runtime


CONTENT = {"story": {
    "id": "s",
    "characters": [{"id": "a", "name": "甲", "is_lead": True}],
    "acts": [{"index": 1, "title": "一"}],
    "locations": [{"id": "l1", "name": "旧巷", "detail": "x", "exits": ["老码头"]},
                  {"id": "dock", "name": "老码头", "detail": "x", "exits": ["旧巷"]},
                  {"id": "pier", "name": "海堤与旧灯塔", "detail": "x", "exits": ["旧巷"]}]}}


def _st():
    st = runtime.default_state()
    st["location_id"] = "l1"
    return st


# ── 拦得住 ────────────────────────────────────────────────────────────────────

def test_a_position_that_walks_to_another_place_is_refused():
    """线上那一条的形状。"""
    assert runtime.position_names_elsewhere(CONTENT, _st(), "跟在甲身后往老码头走") == "老码头"


def test_it_catches_the_short_form_of_a_compound_name():
    """⚠️ 命门就在这里: 剧本把地点注册成「海堤与旧灯塔」, 而散文和姿位一律写「海堤」。
    只认全名的读口对真实文字是瞎的 —— 线上那一拍的漂移遥测正是因此记成了空。"""
    assert runtime.position_names_elsewhere(CONTENT, _st(), "跟在她身后往海堤走") == "海堤与旧灯塔"


def test_standing_in_the_current_place_is_fine():
    """在【此地】自己的名字下走动不算跑题 —— 否则读口全是噪音, 就没人看了。"""
    assert runtime.position_names_elsewhere(CONTENT, _st(), "站在旧巷口的灯下") == ""


def test_ordinary_in_room_posture_passes():
    for t in ("靠在窗边，手插口袋", "坐下，叫碟炒面", "往门口走了一步", "蹲在纸箱旁边"):
        assert runtime.position_names_elsewhere(CONTENT, _st(), t) == "", t


def test_blank_is_quiet():
    assert runtime.position_names_elsewhere(CONTENT, _st(), "") == ""
    assert runtime.position_names_elsewhere(CONTENT, _st(), None) == ""


def test_a_one_character_place_name_never_matches():
    """一个字的地名 (「巷」「街」) 到处误命中 —— 跟散文读口同一条家规。"""
    c = {"story": dict(CONTENT["story"], locations=[
        {"id": "l1", "name": "旧巷", "detail": "x", "exits": []},
        {"id": "x", "name": "街", "detail": "x", "exits": []}])}
    assert runtime.position_names_elsewhere(c, _st(), "沿着街边慢慢走") == ""


# ── 真的没入账 ────────────────────────────────────────────────────────────────

def test_the_refused_position_never_reaches_the_ledger():
    """读口只是读口 —— 这一条验的是它真的接在写入口上, 不是挂在旁边。"""
    st = _st()
    runtime.book_position(CONTENT, st, None, "跟在她身后往海堤走")
    assert st.get("player_pos") in (None, {}), "假姿位还是入账了"


def test_an_honest_position_does_reach_the_ledger():
    """别把 bug 修成功能没了。"""
    st = _st()
    runtime.book_position(CONTENT, st, None, "靠在窗边")
    assert (st.get("player_pos") or {}).get("text") == "靠在窗边"
    assert (st.get("player_pos") or {}).get("at") == "l1", "姿位要钉住是在哪一场记的"


def test_a_character_position_goes_through_the_same_gate():
    st = _st()
    runtime.book_position(CONTENT, st, "a", "往老码头那边走")
    assert not ((st.get("char_sim") or {}).get("a") or {}).get("pos")
    runtime.book_position(CONTENT, st, "a", "手撑着栏杆")
    assert (((st.get("char_sim") or {}).get("a") or {}).get("pos") or {}).get("text") == "手撑着栏杆"
