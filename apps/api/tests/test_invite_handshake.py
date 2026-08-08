# -*- coding: utf-8 -*-
"""🤝 两步握手 = 真移动 (P0 实验的负结果逼出来的改法, 2026-08-08)。

实验打脸: 拿真实存档跑 5 轮 A/B, 「批准回执」组和无回执组【一样】2/5 把人写到了别处。
回执原话是「只演到起身、相邀为止，别写已经到了」, 模型五次里两次照样写到了。

复盘之后我认为那条回执【本身就是错的设计】: 它要求模型做一件违反戏理的事 ——
角色刚说完「要不要跟我去海边」, 玩家刚答「跟她去海边」, 这时候不许到达, 是引擎在跟
故事较劲。而拦住的理由只是「想让玩家再点一次确认条」, 可玩家已经用嘴同意过了。

角色提议 → 玩家答应, 这是【两步握手】, 比点一下地图图标的同意更强。所以:

    上一拍角色邀约了一个在册可达的地方 + 这一拍玩家答应 ⇒ 真的移动过去。

落点在【下一拍开头】而不是双拍的缝里 —— 缝里改状态会跟已经建好的提示词打架
(提示词里写着旧地点)。放在开头, 整套到达管线 (连续性/在场名单/不许重新介绍)
全都吃得到, 一行新逻辑都不用写。

三把锁的边界没破: 目的地仍由引擎验、仍只能是作者写好的地点、模型仍然搬不动人。
变的只是【玩家的同意可以用说的, 不是只能用点的】。
"""
from app.engine import runtime


CONTENT = {"story": {
    "id": "s",
    "characters": [{"id": "a", "name": "甲", "is_lead": True}],
    "acts": [{"index": 1, "title": "一"}],
    "locations": [{"id": "l1", "name": "旧巷", "detail": "x", "exits": ["老码头"]},
                  {"id": "dock", "name": "老码头", "detail": "x", "exits": ["旧巷"]},
                  {"id": "far", "name": "孤岛", "detail": "x", "exits": []}]}}


def _st(**kw):
    st = runtime.default_state()
    st["location_id"] = "l1"
    st["turn_seq"] = 5
    st.update(kw)
    return st


PEND = {"to": "dock", "to_name": "老码头", "by_name": "甲", "at": 5}


# ── 记下邀约 ──────────────────────────────────────────────────────────────────

def test_a_valid_invite_is_remembered():
    st = _st()
    runtime.note_invite(st, {"to": "dock", "to_name": "老码头", "by_name": "甲"})
    p = st.get("pending_invite") or {}
    assert p.get("to") == "dock" and p.get("at") == 5


def test_only_one_pending_invite_at_a_time():
    """后来的邀约盖掉旧的 —— 两张没兑现的邀请同时挂着, 玩家一句「好啊」谁也说不清答的是哪个。"""
    st = _st()
    runtime.note_invite(st, {"to": "dock", "to_name": "老码头", "by_name": "甲"})
    st["turn_seq"] = 6
    runtime.note_invite(st, {"to": "far", "to_name": "孤岛", "by_name": "乙"})
    assert (st.get("pending_invite") or {}).get("to") == "far"


# ── 玩家答应 → 真的走 ─────────────────────────────────────────────────────────

def test_accepting_actually_moves_you():
    st = _st(pending_invite=PEND, turn_seq=6)
    got = runtime.take_invite(CONTENT, st, "好啊，跟你去", "say")
    assert got and got.get("id") == "dock"
    assert st["location_id"] == "dock", "答应了却没走"
    assert not st.get("pending_invite"), "邀约没销账，下一拍会再走一次"


def test_the_same_invite_never_fires_twice():
    st = _st(pending_invite=PEND, turn_seq=6)
    runtime.take_invite(CONTENT, st, "跟你走", "say")
    st["location_id"] = "l1"          # 假装玩家又自己点回来了
    assert runtime.take_invite(CONTENT, st, "跟你走", "say") is None


def test_an_action_channel_counts_too():
    st = _st(pending_invite=PEND, turn_seq=6)
    assert runtime.take_invite(CONTENT, st, "跟他走", "do")


# ── 不许误判 ──────────────────────────────────────────────────────────────────

def test_talking_about_something_else_does_not_move_you():
    """误报最伤: 玩家聊别的却被搬走, 比不搬更糟。"""
    for t in ("你还好吗？", "我坐下", "他刚才说什么", "这条路好走吗", "我看看四周"):
        st = _st(pending_invite=PEND, turn_seq=6)
        assert runtime.take_invite(CONTENT, st, t, "say") is None, t
        assert st["location_id"] == "l1"


def test_declining_clears_the_invite():
    """明确拒绝要销账 —— 挂着不销, 玩家下一句随口一个「走吧」就被搬走了。"""
    for t in ("不去", "算了吧", "我不想去", "下次吧"):
        st = _st(pending_invite=PEND, turn_seq=6)
        assert runtime.take_invite(CONTENT, st, t, "say") is None, t
        assert not st.get("pending_invite"), f"拒绝之后邀约还挂着: {t}"


def test_a_stale_invite_expires():
    """隔了好几拍才说「走吧」, 说的多半不是那件事了。"""
    st = _st(pending_invite=PEND, turn_seq=99)
    assert runtime.take_invite(CONTENT, st, "走吧", "say") is None


def test_no_invite_no_move():
    st = _st(turn_seq=6)
    assert runtime.take_invite(CONTENT, st, "好啊，跟你去", "say") is None
    assert st["location_id"] == "l1"


def test_god_mode_has_no_feet():
    st = _st(pending_invite=PEND, turn_seq=6, mode="god")
    assert runtime.take_invite(CONTENT, st, "跟你走", "say") is None


def test_an_unreachable_destination_is_refused_even_if_it_got_recorded():
    """双保险: 记下来之后地图变了 (通路上锁/地点没解锁), 兑现时要再验一次。"""
    st = _st(pending_invite={"to": "far", "to_name": "孤岛", "by_name": "甲", "at": 5},
             turn_seq=6)
    assert runtime.take_invite(CONTENT, st, "跟你走", "say") is None
    assert st["location_id"] == "l1"


# ── 走完之后, 正文写到达就【不再是撒谎】 ────────────────────────────────────────

def test_after_the_move_arriving_prose_is_honest():
    """这才是这一刀的意义: 从前正文写「到了老码头」是文实分家, 现在它是实话。"""
    st = _st(pending_invite=PEND, turn_seq=6)
    runtime.take_invite(CONTENT, st, "跟你去", "say")
    prose = "你们一路走到老码头，风很大。"
    assert runtime.prose_moved_elsewhere(CONTENT, st, [prose]) == []
    assert runtime.position_names_elsewhere(CONTENT, st, "站在老码头的栈桥边") == ""
