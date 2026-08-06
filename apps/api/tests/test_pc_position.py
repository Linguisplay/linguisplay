# -*- coding: utf-8 -*-
"""📍 玩家自己的身体在玩家所在的地方 (Yi 报障 2026-08-06, 附实况)。

玩家已经在【西九龙警署总部】里, 输入「我走了过去」(走去茶水间那几步), 旁白却把
整段"赶去警署"重演了一遍: 离开蓝信一、穿过两条街、拐过菠萝冰摊、推开玻璃门 ——
而他三秒前刚推开那扇门。

顺着实况把链条拆开 (存档 319ad9ae, 2026-08-06 20:28 的拍):
    玩家在:                loc_q9qp99  西九龙警署总部
    玩家角色 char_position: loc_yn57b7  九龙城区        ← 对不上
    scene_characters:      []                          ← 连自己都不在场
    那几拍的 present_ids:   []                          ← 于是记不进任何人的历史

根因在最上游: char_position 有九级级联 (同行/濒死/威胁/被掳/约定/钉子/作息/sim/兜底),
**没有一级是「这个角色就是玩家本人」**。于是附身模式下, 玩家自己的身体被作息表或兜底
算到了别处 —— 而玩家的真实位置一直老老实实记在 state["location_id"] 里。

连锁后果 (都由这一条来):
  · scene_characters 在新地点返回空 → 到达旁白那一拍 present_ids=[]
  · present_ids=[] 的拍对任何人都不可见 → 模型永远不知道玩家已经到了
  · 模型能看见的最后一拍还是上一个场景 → 它照着那个场景往下写, 于是重演赶路

「玩家自己在哪」是这九级里【最确定】的一件事, 该排第一。
"""
import copy

import pytest

from app.engine import runtime

CONTENT = {"story": {"id": "s",
                     "characters": [
                         {"id": "pc", "name": "蔡妍", "is_lead": True,
                          # 作息把她钉在别处 —— 正是实况里那个 loc_yn57b7
                          "schedule": [{"from_act": 1, "location_id": "l3"}]},
                         {"id": "b", "name": "蓝信一"}],
                     "acts": [{"index": 1, "title": "一"}],
                     "locations": [{"id": "l1", "name": "果栏", "detail": "x", "exits": ["警署"]},
                                   {"id": "l2", "name": "警署", "detail": "x", "exits": ["果栏"]},
                                   {"id": "l3", "name": "九龙城区", "detail": "x", "exits": []}]}}


def _c():
    return copy.deepcopy(CONTENT)


def _st(loc="l2", mode="character"):
    st = runtime.default_state()
    st["location_id"] = loc
    st["player_character_id"] = "pc"
    st["mode"] = mode
    return st


def _pc(c):
    return next(x for x in c["story"]["characters"] if x["id"] == "pc")


# ── 📍 最确定的那一件事 ──────────────────────────────────────────────────
def test_the_players_own_body_is_where_the_player_is():
    """九级级联里最确定的一件事: 玩家自己在哪。实况里它被作息表盖过去了。"""
    c, st = _c(), _st("l2")
    assert runtime.char_position(c, st, _pc(c)) == "l2", \
        "玩家自己的角色被算到了别的地方"


def test_it_beats_the_authors_schedule():
    """作息表是作者写给 NPC 的班表 —— 管不到玩家亲自操纵的这具身体。"""
    c, st = _c(), _st("l1")
    assert runtime.char_position(c, st, _pc(c)) == "l1"


def test_it_follows_the_player_around():
    c, st = _c(), _st("l1")
    assert runtime.char_position(c, st, _pc(c)) == "l1"
    runtime.apply_move(c, st, "警署")
    assert runtime.char_position(c, st, _pc(c)) == "l2", "玩家走了, 身体没跟上"


def test_god_mode_leaves_that_character_to_the_normal_rules():
    """上帝视角下没人在附身 —— 那个角色就是个普通 NPC, 照作息走。"""
    c, st = _c(), _st("l2", mode="god")
    assert runtime.char_position(c, st, _pc(c)) == "l3", \
        "上帝位下不该把那个角色钉在玩家的机位上"


def test_other_characters_are_untouched():
    """只治玩家自己那一具, 别的角色一律照旧走九级级联。"""
    c, st = _c(), _st("l2")
    b = next(x for x in c["story"]["characters"] if x["id"] == "b")
    assert runtime.char_position(c, st, b) != "l2" or True   # 只要不抛
    st["char_pins"] = {"b": "l1"}
    assert runtime.char_position(c, st, b) == "l1", "钉子对别人还该管用"


# ── 🔗 连锁: 到达那一拍必须记得住 ────────────────────────────────────────
def test_the_player_counts_as_present_in_their_own_scene():
    """scene_characters 返回空 → 到达旁白 present_ids=[] → 那一拍对谁都不可见。
    这是"模型不知道玩家已经到了"的直接来源。"""
    c, st = _c(), _st("l2")
    ids = [x.get("id") for x in runtime.scene_characters(c, st)]
    assert "pc" in ids, f"玩家自己都不在自己的场景里: {ids}"


def test_a_beat_from_the_players_own_scene_is_in_their_history():
    c, st = _c(), _st("l2")
    present = [x.get("id") for x in runtime.scene_characters(c, st)]
    log = [{"author": "engine", "type": "description",
            "text": "警署大堂，日光灯管嗡嗡轻响。", "present_ids": present}]
    assert runtime.history_for(log, "pc"), \
        "刚到达那一拍进不了玩家自己的历史 —— 模型下一回合就不知道他已经到了"


# ── 🧪 红样本自验 ────────────────────────────────────────────────────────
def test_red_sample_an_empty_present_list_hides_a_beat_from_everyone():
    """present_ids=[] 的拍对【任何】char_id 都不可见 —— 这条本身是对的
    (没人见证过), 坏就坏在玩家自己本不该缺席。"""
    log = [{"author": "engine", "type": "description", "text": "x", "present_ids": []}]
    assert runtime.history_for(log, "pc") == []
    assert runtime.history_for(log, None) == []
