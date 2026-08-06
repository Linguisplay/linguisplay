# -*- coding: utf-8 -*-
"""🎟 邀约确认条取消 (Yi 2026-08-06 第三刀:「不通过文字控制！」)。

这是 2026-08-04 那两把锁的收尾。前两把关掉之后我实测过一遍, 从文字里长出来的移动
只剩最后一条还活着:
  · 对话现造新地点 → 已死 (generate_and_move 在锁下直接返回 None)
  · 正文写「你到了老码头」→ 已死 (settle_prose_arrival 不改位置)
  · 导演声明 moved_to  → 已死
  · 【角色台词里邀你去一个已在册、已解锁、走得到的地方 → 回合尾弹确认条】← 还活着
    玩家自己在输入框里提到一个已在册的地名, 同样弹。

Yi 的裁定: 移动只剩【点界面】—— 地图面板点节点, 或顶栏「可去：X」点一下。
角色照样可以嘴上邀你, 但要走得玩家自己点。

验红方式跟 test_llm_map_lockdown 一致: 默认就是锁死, 直接跑必绿, 所以每组都配一条
【解锁后确实会弹】的红样本, 证明断言真在守而不是在空转。
"""
import pytest

from app.engine import runtime


@pytest.fixture
def unlocked(monkeypatch):
    """把锁打开 —— 只给红样本用, 证明这条路本来真的会弹确认条。"""
    monkeypatch.setattr(runtime, "INVITE_MOVE", True)


CONTENT = {"story": {
    "id": "s", "sandbox": {"enabled": True},
    "characters": [{"id": "a", "name": "甲", "is_lead": True}],
    "acts": [{"index": 1, "title": "一"}],
    "locations": [{"id": "l1", "name": "旧巷", "detail": "x", "exits": ["老码头"]},
                  {"id": "dock", "name": "老码头", "detail": "x", "exits": ["旧巷"]}]}}


def _st():
    st = runtime.default_state()
    st["location_id"] = "l1"
    return st


# ── 锁本身 ────────────────────────────────────────────────────────────────────

def test_the_lock_is_off_by_default():
    """作者改不了它 —— 它是模块常量, 不是 tuning 键 (跟另外两把一致)。"""
    assert runtime.INVITE_MOVE is False


def test_it_is_not_a_tuning_key():
    assert "invite_move" not in runtime.DEFAULT_TUNING


# ── 邀约不再变成一个能走人的按钮 ────────────────────────────────────────────────

def test_an_invite_to_a_real_place_makes_no_chip():
    assert runtime.invite_chip(CONTENT, _st(), "老码头", "a", "甲") is None


def test_red_sample_it_really_would_have_fired(unlocked):
    """红样本: 解锁后同一个输入确实弹得出来, 证明上一条不是在空转。"""
    got = runtime.invite_chip(CONTENT, _st(), "老码头", "a", "甲")
    assert got and got.get("to") == "dock"


def test_a_place_the_player_named_makes_no_chip():
    assert runtime.invite_chip(CONTENT, _st(), "老码头", None, None) is None


# ── 玩家自己点的那条路必须【毫发无伤】 ──────────────────────────────────────────

def test_tapping_the_map_still_moves_you():
    """地图面板点节点 → apply_move。这条是玩家驱动的, 三把锁一条都不该碰它。"""
    st = _st()
    runtime.apply_move(CONTENT, st, "老码头")
    assert st["location_id"] == "dock"


def test_walking_an_exit_still_works():
    st = _st()
    runtime.apply_move(CONTENT, st, "dock")
    assert st["location_id"] == "dock"


def test_an_unreachable_place_still_refuses():
    """闸没被顺手拆掉: 走不到的地方照旧报错。"""
    c = {"story": dict(CONTENT["story"], locations=[
        {"id": "l1", "name": "旧巷", "detail": "x", "exits": ["老码头"]},
        {"id": "dock", "name": "老码头", "detail": "x", "exits": ["旧巷"]},
        {"id": "far", "name": "孤岛", "detail": "x", "exits": []}])}
    with pytest.raises(ValueError):
        runtime.apply_move(c, _st(), "孤岛")


# ── 打听人在哪: 照旧告诉你, 只是不给按钮 ────────────────────────────────────────

SEEK = {"story": {
    "id": "s",
    "characters": [{"id": "c1", "name": "Mara", "is_lead": True, "home_location_id": "hall"}],
    "acts": [{"index": 1, "title": "一"}],
    "locations": [{"id": "study", "name": "书房", "detail": "x", "exits": ["大厅"]},
                  {"id": "hall", "name": "大厅", "detail": "x", "exits": ["书房"]}]}, "secrets": []}


def test_seeking_still_tells_you_where_they_are():
    """情报本身不是移动 —— 那一拍旁白照发, 行踪照钉, 只是不再附一个能走人的按钮。
    想去自己点地图, 地图上本来就标着谁站在哪。"""
    st = {**runtime.default_state(), "location_id": "study", "act": 1}
    out = runtime.run_turn(SEEK, st, {"name": "我"}, "去找Mara", channel="say")
    assert out.get("move_request") is None, "确认条还在弹"
    assert any("Mara" in (b.get("text") or "") for b in out["beats"]), "连人在哪都不告诉了"
    assert out["state"]["char_pins"] == {"c1": "hall"}, "行踪没钉住"
    assert out["state"]["location_id"] == "study", "居然把人挪走了"


# ── 前两把锁的回归 (这一刀不许把它们碰松) ────────────────────────────────────────

def test_prose_arrival_is_still_dead():
    st = _st()
    runtime.settle_prose_arrival(CONTENT, st, [
        {"type": "description", "text": "你们一路走到了老码头，风很大。"}], "l1", None)
    assert st["location_id"] == "l1"


def test_minting_is_still_dead():
    import copy

    class _L:
        def generate(self, p):
            if p.get("describe_place"):
                return {"name": "河堤", "detail": "水汽"}
            if p.get("risk_judge"):
                return {"risk": 100}
            return {}

    assert runtime.generate_and_move(copy.deepcopy(CONTENT), _st(), "河堤",
                                     llm=_L(), move=False) is None
