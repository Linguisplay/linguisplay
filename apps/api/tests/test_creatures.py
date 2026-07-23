# -*- coding: utf-8 -*-
"""🐲 生物账本 P0 (Yi 拍板 2026-07-20): 第三实体类 — D&D stat block + MH 血阶行为。
执法点: 命中要骰面背书 · 鬼打不死 · 段位碾压 · 重创激怒 · 濒死逃巢 · 讨伐剥取入包 ·
图鉴只列见过的。"""

from app.engine import runtime

STORY = {
    "story": {"id": "s",
              "characters": [{"id": "a", "name": "甲", "is_lead": True}],
              "acts": [{"index": 1, "title": "一"}],
              "locations": [{"id": "camp", "name": "营地", "detail": "篝火", "exits": ["林地"]},
                            {"id": "woods", "name": "林地", "detail": "古树", "exits": ["营地", "巢穴"]},
                            {"id": "nest", "name": "巢穴", "detail": "白骨", "exits": ["林地"]}],
              "creatures": [
                  {"id": "wyv", "name": "青鳞火龙", "kind": "龙", "menace": 1,
                   "desc": "鳞如淬火的青铜", "habits": "护巢，怕烟",
                   "lair": "nest", "territory": ["woods"],
                   "drops": [{"name": "青鳞", "detail": "还带着余温"},
                             {"name": "龙尾骨", "detail": "沉手"}]},
                  {"id": "ghost", "name": "无面妇人", "kind": "鬼", "killable": False,
                   "menace": 9, "speech": "fragments", "lair": "nest",
                   "desc": "她没有脸", "habits": "在雾里跟着人", "drops": []}]},
    "secrets": [],
}


def _st(loc="woods"):
    st = runtime.default_state()
    st["location_id"] = loc
    # 把龙放到林地 (领地巡游简化: 测试直接摆位)
    runtime._cr_sim(st, "wyv", {"lair": "nest"})["pos"] = loc
    return st


def test_presence_and_bestiary_seen_gate():
    st = _st()
    here = runtime.creatures_here(STORY, st)
    assert any(c["name"] == "青鳞火龙" for c in here)
    bv = runtime.bestiary_view(STORY, st)
    assert len(bv["rows"]) >= 1 and bv["unseen"] >= 1   # 鬼没遭遇过 → 只计数不剧透
    assert "bestiary" in runtime.phone_apps(STORY)       # 有生物的世界自动有图鉴


def test_hit_needs_dice_and_ladder_behaviors():
    st = _st()
    # 无骰不认
    assert runtime.apply_creature_hit(STORY, st, "青鳞火龙|尾|重伤", None) is None
    ok = {"outcome": "success"}
    # 重伤两次: 带伤→重创 → 引擎自动激怒
    runtime.apply_creature_hit(STORY, st, "青鳞火龙|尾|重伤", ok)
    ev = runtime.apply_creature_hit(STORY, st, "青鳞火龙|翼|重伤", ok)
    assert ev["hp"] == "重创" and ev.get("enraged")
    assert st["creature_sim"]["wyv"]["enraged"]
    # 第三次重伤: 濒死 → 逃回巢穴 (真实移动)
    ev = runtime.apply_creature_hit(STORY, st, "青鳞火龙|腿|重伤", ok)
    assert ev.get("fled") == "巢穴" and st["creature_sim"]["wyv"]["pos"] == "nest"
    # 它不在场了 → 打不着
    assert runtime.apply_creature_hit(STORY, st, "青鳞火龙|头|重伤", ok) is None
    # 追到巢穴补刀 → 讨伐
    st["location_id"] = "nest"
    ev = runtime.apply_creature_hit(STORY, st, "青鳞火龙|头|重伤", ok)
    assert ev.get("slain")


def test_ghost_and_menace_gates():
    st = _st()
    runtime._cr_sim(st, "ghost", {"lair": "woods"})["pos"] = "woods"
    ok = {"outcome": "crit_success"}
    ev = runtime.apply_creature_hit(STORY, st, "无面妇人|头|重伤", ok)
    assert ev.get("ghost")                                # 打不死的东西
    assert not (st["creature_sim"]["ghost"].get("hp"))
    # 段位碾压: menace 9 vs rank 0 — 换只 killable 的高威胁怪验证
    story2 = {"story": {**STORY["story"], "creatures": [
        {"id": "eld", "name": "灭尽龙", "kind": "龙", "menace": 5,
         "lair": "woods", "drops": []}]}, "secrets": []}
    st2 = runtime.default_state()
    st2["location_id"] = "woods"
    runtime._cr_sim(st2, "eld", {"lair": "woods"})["pos"] = "woods"
    ev2 = runtime.apply_creature_hit(story2, st2, "灭尽龙|头|重伤", ok)
    assert ev2.get("no_dent")                             # 毫发无伤是账本事实


def test_carve_grants_drops_once_with_wound_bonus():
    st = _st()
    sim = st["creature_sim"]["wyv"]
    sim.update({"hp": 4, "wounds": ["尾"], "pos": "woods"})
    got = runtime.carve_creature(STORY, st, "剥取素材", "do")
    assert any(g["name"] == "青鳞" and g["qty"] == 2 for g in got)   # 部位破坏头件翻倍
    names = [i.get("name") for i in st.get("inventory") or []]
    assert "青鳞" in names and "龙尾骨" in names
    assert runtime.carve_creature(STORY, st, "再剥一次", "do") == []  # 只许剥一次
