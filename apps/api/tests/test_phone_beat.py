# -*- coding: utf-8 -*-
"""📱 回复的【时机与形状】收归引擎 (Yi 2026-08-05:「角色在手机上的互动和记忆非常重要，
这部分现在太落后了」)。

生产实况 (176 个存档全扫, 125 条消息): 设计了四种回复形状, 但【已读晾着 0 次、
4~5 条刷屏 0 次】; 打电话 0 次; 延迟投递 0 个线程; 所有消息都在第 1 天、时间戳挤在
同一分钟里 —— 全是秒回。

亲验出来的真相分三层, 不是一个原因:
  ① 刷屏 = 100% 死码。qwen.py 解析器 `msgs[:3]` 硬截成 3 条, 而判 burst 要 `>=4` ——
     两行互斥, 提示词里那句「四五条短的连着发」写了也送不出来。
  ② 已读·短写法 = 静默吞掉。解析器 `("已读" in s) and len(s) <= 6` 命中就 break:
     msgs 清空、第二行的「稍后：」整条丢弃、last_read 不写、metrics 记成 normal。
  ③ 已读·长写法 =【能通】(else 分支只剥圆括号和引号, 不动【】), 但模型从没选过它。

③ 才是本文件要治的病根: 四种形状并列给模型自选, 它永远选中庸的那一档。本仓一贯的
教条是【引擎判定, 模型写词】—— 导演、乐师、骰子都是这么做的, 唯独回复形状交了出去。

合并设计 (来自四路探查 + 判官合稿): **一个 _phone_beat() 一次返回 (tier, shape)**,
而不是两条各读同样信号却给出相反结论的阶梯。硬互斥表:
  · shape == "read"  ⇒ tier 强制 now   (read 本身就是"不回", 不许再叠一层延迟)
  · tier  != "now"   ⇒ shape 不许是 read
  · 线程上还欠着债 (last_read 或 pending 非空) ⇒ 强制 now 且不许 read
    —— 一条线程任何时刻最多欠一笔债; 连着两次不回, 玩家读到的是「坏了」不是「TA在气我」
"""
import copy

import pytest

from app.engine import runtime

STORY = {"story": {"id": "s", "phone": {"enabled": True, "device": "手机"},
                   "characters": [
                       {"id": "a", "name": "甲", "is_lead": True},
                       {"id": "b", "name": "乙"},
                       {"id": "z", "name": "丙"}],
                   "acts": [{"index": 1, "title": "一"}],
                   "locations": [{"id": "l1", "name": "旧巷", "detail": "x", "exits": []}]}}


def _st(**kw):
    st = runtime.default_state()
    st["location_id"] = "l1"
    st["met_ids"] = ["b", "z"]
    st["contact_ids"] = ["b", "z"]
    st.update(kw)
    return st


def _c(content, cid="b"):
    # ⚠️ 必须从【传进来的那份 content】取角色, 不能图省事从模块级 STORY 取 ——
    #    否则给某个角色加了 schedule 的用例, 送进 _phone_beat 的还是那个没作息的
    #    副本, 判据永远不命中, 测试静静空转 (实弹: 作息 AWAY 那条为此白红了一轮)。
    return next(x for x in content["story"]["characters"] if x["id"] == cid)


def _beat(st, cid="b", text="在吗", here=False, content=None):
    content = content or copy.deepcopy(STORY)
    th = runtime._thread(st, cid)
    return runtime._phone_beat(content, st, _c(content, cid), text, here, th)


# ── 🔒 契约: 一次返回两样, 且值域封闭 ──────────────────────────────────────
def test_returns_a_tier_and_a_shape():
    tier, shape = _beat(_st())
    assert tier in runtime.PHONE_TIERS, f"未知档位 {tier!r}"
    assert shape in runtime.PHONE_SHAPES, f"未知形状 {shape!r}"


def test_the_plain_default_is_deterministic_now_normal():
    """默认档必须确定性命中 (now, normal) —— 否则既有契约测试会【间歇】红。

    实弹提醒 (判官抓到的): tests/test_phone.py:109 断言回复逐字全等
    ["在吗","睡不着。","你呢？"]。判定里一旦掷骰, 那条会变成 flaky ——
    间歇红比确定红难查十倍。所以硬信号一律不掷骰。"""
    for _ in range(20):
        assert _beat(_st()) == ("now", "normal")


# ── 🚦 tier: 什么时候不该立刻回 ────────────────────────────────────────────
def test_same_room_always_answers_now():
    assert _beat(_st(), here=True)[0] == "now"


def test_a_companion_walking_with_you_answers_now():
    assert _beat(_st(following=["b"]))[0] == "now"


def test_the_dead_never_answer():
    st = _st()
    runtime._sim(st, "b")["hp"] = "dead"
    assert _beat(st)[0] == "never"


def test_the_authors_schedule_wins_over_everything_soft():
    """作者班表说这个钟点找不到 TA —— 不许软化成"隔一阵", 下个时段班表自然恢复。"""
    content = copy.deepcopy(STORY)
    content["story"]["characters"][1]["schedule"] = [{"from_act": 1, "location_id": "l1",
                                                      "slots": ["晨"]}]
    st = _st()
    st["clock"] = {"day": 1, "slot": 2, "turns_in_slot": 0}   # 夜: 班表没覆盖 → AWAY
    tier, _ = _beat(st, content=content)
    assert tier == "next_slot", f"班表 AWAY 应判 next_slot, 得到 {tier}"


def test_someone_pinned_elsewhere_replies_later_not_never():
    """引擎那颗"走出了这一场"的钉子不是关机 —— 只是慢, 不是不回。
    (老实弹: 角色说句「我先走了」, 这电话就永久打不通。)"""
    st = _st()
    st["char_pins"] = {"b": runtime.AWAY}
    assert _beat(st)[0] == "later"


def test_busy_with_an_errand_replies_later():
    st = _st()
    runtime._sim(st, "b")["intent"] = "去码头取一件东西"
    # ⏳ 应承有保质期: 没盖 intent_at 的一律当过期。char_sim["intent"] 全仓原本没有
    #    任何清除点, 于是说过一次差事的角色【此后每一条短信都判 later】, 永远慢半拍
    #    (2026-08-05 对抗验收抓出)。老档从宽, 新写的都盖章。
    runtime._sim(st, "b")["intent_at"] = runtime._time_index(st)
    assert _beat(st)[0] == "later"


def test_a_stale_errand_stops_slowing_them_down():
    st = _st()
    runtime._sim(st, "b")["intent"] = "去码头取一件东西"
    runtime._sim(st, "b")["intent_at"] = runtime._time_index(st) - 9
    assert _beat(st)[0] == "now", "几天前应承的事还在拖慢每一条短信"


# ── 🌙 深夜 ────────────────────────────────────────────────────────────────
def test_deep_night_a_stranger_answers_in_the_morning():
    st = _st()
    st["clock"] = {"day": 1, "slot": 2, "turns_in_slot": 0, "real": "03:20"}
    tier, _ = _beat(st, content=_real_clock_story())
    assert tier == "morning", f"深夜陌生人该明早回, 得到 {tier}"


def test_deep_night_a_lover_still_answers_soon():
    """睡不着的人只为一个人爬起来。"""
    st = _st(rel={"b": {"closeness": 70, "romance": 70}})
    st["clock"] = {"day": 1, "slot": 2, "turns_in_slot": 0, "real": "03:20"}
    tier, _ = _beat(st, content=_real_clock_story())
    assert tier == "soon", f"深夜恋人该很快回, 得到 {tier}"


def _real_clock_story():
    c = copy.deepcopy(STORY)
    c["story"]["tuning"] = {"real_clock": 1, "turns_per_slot": 3}
    return c


# ── 💳 一条线程最多欠一笔债 (判官定的硬规矩) ───────────────────────────────
def test_an_outstanding_read_receipt_forces_an_answer_now():
    st = _st()
    th = runtime._thread(st, "b")
    th["last_read"] = {"reason": "在气你", "at": 0}
    runtime._sim(st, "b")["intent"] = "去码头取一件东西"   # 本来该判 later
    tier, shape = _beat(st)
    assert tier == "now", "上次已经晾过, 这次必须还债"
    assert shape != "read", "连着晾两次 = 玩家以为坏了"


def test_a_pending_message_also_forces_an_answer_now():
    st = _st()
    runtime._thread(st, "b")["pending"] = [{"text": "等下说", "due_ts": 1}]
    runtime._sim(st, "b")["intent"] = "去码头取一件东西"
    assert _beat(st)[0] == "now"


# ── ⚔️ 硬互斥表 ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("seed_kw", [
    {"char_pins": {"b": runtime.AWAY}},
    {},
])
def test_read_and_delay_never_stack(seed_kw):
    """read 本身就是"不回", 不许再叠一层延迟; 反过来延迟也不许再挑 read。"""
    st = _st(**seed_kw)
    tier, shape = _beat(st)
    if shape == "read":
        assert tier == "now", "已读晾着又叠延迟 = 玩家一次发送看到两条已读"
    if tier != "now":
        assert shape != "read", "延迟里不许再挑 read"


def test_every_reachable_combination_obeys_the_table():
    """把能构造的状态组合跑一遍, 断言互斥表永远成立 (穷举式守卫)。"""
    combos = []
    for pins in ({}, {"b": runtime.AWAY}):
        for intent in ("", "去办事"):
            for lr in (None, {"reason": "在气你", "at": 0}):
                for rel in ({}, {"b": {"closeness": 70, "romance": 70}}):
                    st = _st(rel=dict(rel), char_pins=dict(pins))
                    if intent:
                        runtime._sim(st, "b")["intent"] = intent
                    if lr:
                        runtime._thread(st, "b")["last_read"] = dict(lr)
                    combos.append(_beat(st))
    assert combos, "一个组合都没跑到"
    for tier, shape in combos:
        assert tier in runtime.PHONE_TIERS and shape in runtime.PHONE_SHAPES
        assert not (shape == "read" and tier != "now")
        assert not (tier != "now" and shape == "read")


# ── 🧪 红样本自验 ─────────────────────────────────────────────────────────
def test_red_sample_the_burst_shape_used_to_be_physically_impossible():
    """修复前 qwen 解析器把回复硬截成 3 条, 而判 burst 要 >=4 —— 死码。"""
    truncated = ["a", "b", "c", "d", "e"][:3]
    assert len(truncated) < 4, "红样本本身就该证明 burst 到不了"


def test_the_parser_no_longer_truncates_below_the_burst_line():
    """修完之后, 解析器留的余量必须够 burst 用。"""
    import re
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "app" / "engine" / "qwen.py").read_text(encoding="utf-8")
    m = re.search(r'"msgs":\s*msgs\[:(\d+)\]', src)
    assert m, "没找到 phone_reply 的截断处"
    assert int(m.group(1)) >= 5, \
        f"解析器只留 {m.group(1)} 条 — 判 burst 要 >=4, 刷屏又成死码了"
