# -*- coding: utf-8 -*-
"""🎟 邀约确认条开回来 (Yi 2026-08-08 拍板)。

2026-08-06 第三刀把它关了, 理由是「不通过文字控制！」。两天后线上抓到这一拍
(存档 ca3f993b, 剧本樱见坂, 就发生在当天的修复上线之后):

    角色：要不要跟我去海边透透气，这个点堤防没人，浪声可大了。
    玩家：跟她去海边
    旁白：海堤的风比商店街大得多⋯⋯她走在前面，围裙都没解⋯⋯

而 location_id 一动没动。审计单显示当天新做的三道东西【全部正常工作】:
意图认出来了、toast 弹了 (map_move)、move_blocked 也下给模型了。模型照样把人写走。

根因不在提示词强度, 在【我们把出口堵死了, 只留下一条禁令】: 角色能开口邀约, 玩家
能开口答应, 而系统没有任何办法兑现。模型手上有戏要演, 就翻墙。

所以开回来的是【一个玩家必须亲手点的按钮】—— 仍然符合「移动只剩点界面」:
  · 角色申报 move_invite → 引擎验目的地在册/已解锁/走得到 → 弹确认条
  · 玩家点「跟 TA 去」才真的走; 点「留下」就留下
另外两把锁【一动不动】: 散文不许改地图 (LLM_MAP_WRITES), 打字不许改地图 (TYPED_MOVE)。
本文件下半截就是守这一条 —— 开一把不许顺手松另外两把。
"""
import copy

import pytest

from app.engine import qwen, runtime


CONTENT = {"story": {
    "id": "s", "sandbox": {"enabled": True},
    "characters": [{"id": "a", "name": "甲", "is_lead": True}],
    "acts": [{"index": 1, "title": "一"}],
    "locations": [{"id": "l1", "name": "旧巷", "detail": "x", "exits": ["老码头"]},
                  {"id": "dock", "name": "老码头", "detail": "x", "exits": ["旧巷"]},
                  {"id": "far", "name": "孤岛", "detail": "x", "exits": []}]}}


def _st():
    st = runtime.default_state()
    st["location_id"] = "l1"
    return st


# ── 锁本身 ────────────────────────────────────────────────────────────────────

def test_the_invite_lock_is_open():
    assert runtime.INVITE_MOVE is True


def test_the_other_two_locks_stay_shut():
    """这一刀只开邀约那一把。散文/打字改地图仍然是死的。"""
    assert runtime.LLM_MAP_WRITES is False
    assert runtime.TYPED_MOVE is False


def test_it_is_still_not_a_tuning_key():
    """作者改不了它 —— 模块常量, 跟另外两把一致。"""
    assert "invite_move" not in runtime.DEFAULT_TUNING


# ── 确认条: 该弹的弹, 该拦的还拦 ────────────────────────────────────────────────

def test_an_invite_to_a_reachable_place_makes_a_chip():
    got = runtime.invite_chip(CONTENT, _st(), "老码头", "a", "甲")
    assert got and got.get("to") == "dock"
    assert got.get("by_name") == "甲", "确认条上要写清是谁邀的"


def test_an_unreachable_place_still_makes_no_chip():
    """在册但此地走不到 —— 不造玩家点了会报错的垃圾条。"""
    assert runtime.invite_chip(CONTENT, _st(), "孤岛", "a", "甲") is None


def test_a_place_that_does_not_exist_mints_nothing():
    """铸地那半边归 LLM_MAP_WRITES 管, 这一刀没碰它。"""
    class _L:
        def generate(self, p):
            if p.get("describe_place"):
                return {"name": "河堤", "detail": "水汽"}
            if p.get("risk_judge"):
                return {"risk": 100}
            return {}

    assert runtime.invite_chip(copy.deepcopy(CONTENT), _st(), "河堤",
                               "a", "甲", llm=_L()) is None


# ── 整拍走一遍 (线上就是这个旗组合: 只有邀约开着) ──────────────────────────────

class _InviteLLM:
    """一个照着提示词老实申报 move_invite 的模型。"""

    def __init__(self, dest):
        self.dest = dest

    def generate(self, prompt):
        if prompt.get("describe_place"):
            return {"name": (prompt.get("place_name") or "")[:12], "detail": "x"}
        if prompt.get("intro") or prompt.get("observe") or prompt.get("suggest"):
            return {"beats": [{"type": "description", "speaker_name": None, "text": "x"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}
        return {"beats": [{"type": "dialogue", "speaker_name": prompt.get("speaker_name"),
                           "text": "走，带你去。"}],
                "affinity_delta": 0, "advance_act": False, "ending": None,
                "move_invite": self.dest}


def test_an_invite_becomes_a_chip_and_does_not_move_anyone():
    """⚠️ 这一条是全文件唯一在【线上那套旗】下跑完整拍的用例。单测只验提示词字符串
    是不够的 —— 2026-08-08 那个分派键撞名的事故, 1300 条单测全绿, 只有整拍跑得出来。"""
    st = _st()
    out = runtime.run_turn(CONTENT, st, {"name": "我"}, "在吗", channel="say",
                           llm=_InviteLLM("老码头"))
    req = out.get("move_request") or {}
    assert req.get("to") == "dock", "角色申报了带路, 却没弹确认条"
    assert out["state"]["location_id"] == "l1", "没等玩家点就把人挪走了"


def test_an_invite_to_an_unreachable_place_makes_no_chip_end_to_end():
    st = _st()
    out = runtime.run_turn(CONTENT, st, {"name": "我"}, "在吗", channel="say",
                           llm=_InviteLLM("孤岛"))
    assert out.get("move_request") is None
    assert out["state"]["location_id"] == "l1"


# ── 另外两把锁的回归 (开一把不许松两把) ────────────────────────────────────────

def test_typing_a_destination_still_moves_nobody():
    """玩家自己在输入框里点名一个地点, 既不走人也不弹条 —— 那是 TYPED_MOVE 的地盘,
    这一刀没碰它。(确认条只由【角色的邀约】发起。)"""
    st = _st()
    out = runtime.run_turn(CONTENT, st, {"name": "我"}, "我去老码头", channel="say")
    assert st["location_id"] == "l1", "TYPED_MOVE 被顺手拆松了"
    assert out.get("move_request") is None, "玩家打字也弹条了 —— 那是另一把锁"


def test_prose_arrival_is_still_dead():
    st = _st()
    runtime.settle_prose_arrival(CONTENT, st, [
        {"type": "description", "text": "你们一路走到了老码头，风很大。"}], "l1", None)
    assert st["location_id"] == "l1"


def test_minting_is_still_dead():
    class _L:
        def generate(self, p):
            if p.get("describe_place"):
                return {"name": "河堤", "detail": "水汽"}
            if p.get("risk_judge"):
                return {"risk": 100}
            return {}

    assert runtime.generate_and_move(copy.deepcopy(CONTENT), _st(), "河堤",
                                     llm=_L(), move=False) is None


def test_tapping_the_map_still_moves_you():
    st = _st()
    runtime.apply_move(CONTENT, st, "老码头")
    assert st["location_id"] == "dock"


def test_walking_an_exit_still_works():
    st = _st()
    runtime.apply_move(CONTENT, st, "dock")
    assert st["location_id"] == "dock"


def test_an_unreachable_place_still_refuses():
    with pytest.raises(ValueError):
        runtime.apply_move(CONTENT, _st(), "孤岛")


# ── 打听人在哪: 同一口闸, 所以那张条也跟着回来了 ────────────────────────────────

SEEK = {"story": {
    "id": "s",
    "characters": [{"id": "c1", "name": "Mara", "is_lead": True, "home_location_id": "hall"}],
    "acts": [{"index": 1, "title": "一"}],
    "locations": [{"id": "study", "name": "书房", "detail": "x", "exits": ["大厅"]},
                  {"id": "hall", "name": "大厅", "detail": "x", "exits": ["书房"]}]}, "secrets": []}


def test_seeking_someone_offers_a_go_find_them_chip():
    """⚠️ 记在这里别装作没有: 「去找 TA」这张条跟邀约条共用 INVITE_MOVE 这一把锁,
    所以开邀约就一起回来了。Yi 若只想要邀约那一半, 改的是 seek 那一处的条件, 不是锁。"""
    st = {**runtime.default_state(), "location_id": "study", "act": 1}
    out = runtime.run_turn(SEEK, st, {"name": "我"}, "去找Mara", channel="say")
    req = out.get("move_request") or {}
    assert req.get("seek") and req.get("to") == "hall"
    assert any("Mara" in (b.get("text") or "") for b in out["beats"]), "连人在哪都不告诉了"
    assert out["state"]["char_pins"] == {"c1": "hall"}, "行踪没钉住"
    assert out["state"]["location_id"] == "study", "还没点条就把人挪走了"


# ── 提示词层: 出口和禁令必须是同一套说法 ────────────────────────────────────────

def _sys(**kw):
    p = {"speaker_name": "甲", "speaker_persona": "x", "channel": "say",
         "persona": {"name": "我"}, "context": {}, "place": "旧巷"}
    p.update(kw)
    return qwen._build_system(p)


def test_the_model_is_taught_the_invite_field_again():
    s = _sys()
    assert "move_invite" in s, "锁开着却不教申报, 模型只能用散文兑现"
    assert "征求玩家同意" in s or "玩家点头" in s


def test_the_friction_line_points_at_the_invite_not_the_map():
    """⚠️ 这一条是这次改动最容易漏的接缝: move_blocked 那段原话是「换场只能由玩家
    自己点地图」。锁开了它还这么说, 就是两张嘴对模型讲两套流程 —— 一边教它申报
    move_invite, 一边说申报没用。"""
    s = _sys(move_blocked=True)
    assert "仍然发生在此地" in s, "这一拍留在原地的硬规矩不许丢"
    assert "只能由玩家自己点地图" not in s, "锁开了还在说旧流程"
    assert "move_invite" in s


def test_the_character_may_still_agree_out_loud():
    """不许把角色演成拒绝 —— 玩家说「跟你走」角色回「不行」是另一种坏。"""
    s = _sys(move_blocked=True)
    assert any(k in s for k in ("答应", "起身", "相邀", "招手"))


def test_no_flag_no_friction_block():
    assert "玩家说要走" not in _sys()
