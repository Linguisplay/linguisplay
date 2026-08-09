# -*- coding: utf-8 -*-
"""📷 生图频率交给玩家 (Yi 2026-08-06:「自拍图片之类的生成的频率交给玩家控制」)。

从前只有作者侧的 tuning.snap_chance (缺省 12%) + 引擎写死的 5 个来回冷却, 玩家一点
话语权没有。而这件事恰恰该玩家说了算, 两个理由都硬:
  · 花的是真钱 —— 火山刚刚因为余额见底停过一天生图;
  · 口味差得远 —— 有人就想多看几张, 有人嫌照片打断读文。

四档 (存 state["snap_pref"], 与「活世界」同一路: 服务端 per-run, 不是客户端偏好 ——
判定在引擎里, 客户端存了也管不着):
    0 关     一张都不出
    1 少     概率减半, 冷却拉长到 10 个来回
    2 正常   剧本自己的 snap_chance, 冷却 5 (缺省, 老档逐位不变)
    3 多     概率翻倍 (封顶 60%), 冷却缩到 3

⚠️ 顺带补一个我自己挖的洞: maybe_snap 在 `if msgs:` 里, 而延迟分支【在它之前就
return 了】—— 判了延迟的回复永远不会带照片。而"TA 在外面办事"恰恰是最该拍一张
「我在这儿呢」的时候。
"""
import copy

import pytest

from app.engine import runtime

STORY = {"story": {"id": "s", "phone": {"enabled": True, "device": "手机"},
                   "tuning": {"turns_per_slot": 6, "snap_chance": 20},
                   "characters": [{"id": "a", "name": "甲", "is_lead": True},
                                  {"id": "b", "name": "乙", "persona_text": "寡言的码头工"}],
                   "acts": [{"index": 1, "title": "一"}],
                   "locations": [{"id": "l1", "name": "旧巷", "detail": "x", "exits": ["码头"]},
                                 {"id": "l2", "name": "码头", "detail": "x", "exits": ["旧巷"]}]}}


@pytest.fixture(autouse=True)
def _image_backend(monkeypatch):
    """maybe_snap 第一道闸是"有没有生图后端" —— 测试环境默认 mock, 不放开的话
    整个函数直接返回 None, 下面所有断言都在空转。"""
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "qwen", raising=False)
    monkeypatch.setattr(s, "ark_api_key", "test-key", raising=False)
    get_settings.cache_clear() if hasattr(get_settings, "cache_clear") else None
    monkeypatch.setattr(runtime, "get_settings", lambda: s)


def _st(**kw):
    st = runtime.default_state()
    st["location_id"] = "l1"
    st["met_ids"] = ["b"]
    st["contact_ids"] = ["b"]
    st["clock"] = {"day": 1, "slot": 1, "turns_in_slot": 0}
    st.update(kw)
    return st


def _c():
    return STORY["story"]["characters"][1]


def _rolls(st, n=400):
    """摇 n 次, 数出了几张 —— 冷却也一并生效, 所以量的是【实际产出率】。"""
    c = copy.deepcopy(STORY)
    hits = 0
    for _ in range(n):
        if runtime.maybe_snap(c, st, _c(), "在码头"):
            hits += 1
    return hits


# ── 🎚 四档 ────────────────────────────────────────────────────────────────
def test_off_means_not_a_single_one():
    st = _st(snap_pref=0)
    assert _rolls(st) == 0, "关了还在出图 — 这是真花钱的"


def test_the_default_keeps_todays_behaviour():
    """不设就是"正常" —— 老档逐位不变。"""
    st_none, st_norm = _st(), _st(snap_pref=2)
    a, b = _rolls(st_none), _rolls(st_norm)
    assert abs(a - b) <= max(4, a // 3), f"缺省档跟「正常」不是一回事: {a} vs {b}"


def test_more_really_gives_more_than_fewer():
    few, many = _rolls(_st(snap_pref=1)), _rolls(_st(snap_pref=3))
    assert many > few, f"「多」没比「少」多: 多{many} 少{few}"


def test_the_ladder_is_monotonic():
    got = [_rolls(_st(snap_pref=p)) for p in (0, 1, 2, 3)]
    assert got[0] == 0
    assert got[1] <= got[2] <= got[3], f"四档不是单调的: {got}"


def test_a_junk_preference_falls_back_to_normal():
    for bad in ("x", -3, 99, None, 2.7):
        st = _st(snap_pref=bad)
        assert runtime.snap_pref_of(st) in (0, 1, 2, 3), f"脏值 {bad!r} 没归一"


# ── 🔌 玩家真的能改 ───────────────────────────────────────────────────────
def test_the_setter_round_trips():
    st = _st()
    assert runtime.set_snap_pref(st, 0) == 0
    assert runtime.snap_pref_of(st) == 0
    assert runtime.set_snap_pref(st, 3) == 3
    assert runtime.snap_pref_of(st) == 3


def test_the_setter_refuses_junk():
    st = _st()
    runtime.set_snap_pref(st, 2)
    for bad in ("x", 9, -1, None):
        runtime.set_snap_pref(st, bad)
        assert runtime.snap_pref_of(st) in (0, 1, 2, 3)


# ── 🕳 顺带补洞: 延迟的回复也该能带照片 ──────────────────────────────────
class Reply:
    def __init__(self):
        self.prompts = []

    def generate(self, p):
        self.prompts.append(p)
        if p.get("phone_reply"):
            return {"msgs": ["在码头呢。"], "closeness": 0, "romance": 0}
        return {}


def test_a_delayed_reply_can_still_carry_a_photo(monkeypatch):
    """「TA 在外面办事」正是最该拍一张的时候, 而延迟分支从前在 maybe_snap 之前
    就 return 了 —— 判了延迟的回复永远不会带照片 (我自己挖的洞)。"""
    monkeypatch.setattr(runtime, "maybe_snap",
                        lambda *a, **k: {"url": "/scene/snap/x.jpg", "prompt": "p"})
    c, st = copy.deepcopy(STORY), _st(snap_pref=3)
    st["char_pins"] = {"b": "l2"}
    # ⚠️ 2026-08-09 起「手上有个打算」不再是延迟的理由（self_intent 几乎每拍都填，
    #    于是角色永远不方便回消息）。延迟机制本身没动——这里换一个【真有事】的
    #    理由来触发：作者班表说此刻联系不上。
    runtime._pin_away(st, "b") if hasattr(runtime, "_pin_away") else st.setdefault("char_pins", {}).update({"b": runtime.AWAY})
    view = runtime.phone_send(c, st, {"name": "我"}, "b", "你在哪", llm=Reply())
    pend = ((st.get("phone") or {}).get("threads") or {})["b"].get("pending") or []
    assert pend, "夹具没走到延迟分支"
    assert any(p.get("img") for p in pend), \
        f"延迟的回复带不了照片: {pend}"
    assert view.get("snap"), "路由拿不到要渲染的图"


def test_the_photo_arrives_with_the_message_not_before():
    """照片要跟那条消息【一起】到 —— 提前出现等于剧透 TA 在哪。"""
    import copy as _c2
    c, st = _c2.deepcopy(STORY), _st()
    th = runtime._thread(st, "b")
    th["pending"] = [{"text": "喏，就这儿。", "due_ts": runtime._wall_ts() - 1,
                      "img": "/scene/snap/y.jpg"}]
    runtime.deliver_due_phone(c, st)
    got = [m for m in th["msgs"] if m.get("from") == "them"]
    assert got and got[-1].get("img") == "/scene/snap/y.jpg", \
        f"投递时把照片弄丢了: {got}"
