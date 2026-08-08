# -*- coding: utf-8 -*-
"""⏰ 时间只有一个权威 (Yi 2026-08-08:「reality wins」)。

生产实弹 (存档 c3754b39, 剧本九龙城寨·狗笼):
    剧本  sandbox.real_time = True     现实同步开着
    幕 1  time = {slot: '夜'}          作者又钉死了「夜」
    开场白「夜色沉落，龙津道灯火零落」

玩家 16:34 开局:
    seq 15  引擎的钟 = 夜   ← align_clock_to_act 刚把钟拨过去
    seq 19  引擎的钟 = 午   ← sync_real_clock 按墙上时钟重算, 把锚冲掉了

时间从夜倒回下午, 正文跟着从「夜色沉落」改成「午后的日头」。玩家看到的世界基本事实
在拍与拍之间跳 —— 这就是「回答的逻辑总是不对」的地基。

sync_real_clock 里本来就有一道单调护栏, 注释写明了倒流的危害 (到期的约定会在
open↔missed 之间翻面), 但它【只护了 day, 没护 slot】。

Yi 拍板: 现实赢。开着现实同步的剧本, 作者的 act.time 不再拨钟 —— 一个字段一个权威。
"""
from app.engine import runtime


def _story(real, act_time):
    return {"story": {
        "id": "s",
        "sandbox": {"enabled": True, "real_time": real},
        "characters": [{"id": "a", "name": "甲", "is_lead": True}],
        "acts": [{"index": 1, "title": "一", "time": act_time}],
        "locations": [{"id": "l1", "name": "旧巷", "detail": "x", "exits": []}]}}


def _st(day, slot):
    st = runtime.default_state()
    st["location_id"] = "l1"
    st["act"] = 1
    st["clock"] = {"day": day, "slot": slot}
    return st


def test_the_authors_act_time_no_longer_moves_a_real_clock():
    """⚠️ 这一条是那个 bug 本身。现实同步开着时, 幕锚不许拨钟 ——
    它拨完下一拍就会被现实冲掉, 净效果只是让时间跳一下。"""
    c = _story(True, {"day": 0, "slot": "夜"})
    st = _st(1, 1)                      # 现在是「午」
    assert runtime.align_clock_to_act(c, st, 1) is None, "现实同步下幕锚还在拨钟"
    assert (st.get("clock") or {}).get("slot") == 1, "钟被拨走了"


def test_the_act_anchor_still_works_on_a_fictional_clock():
    """没开现实同步的剧本, 作者说第几天什么时辰就是什么时辰 —— 这条没动。"""
    c = _story(False, {"day": 0, "slot": "夜"})
    st = _st(1, 0)                      # 现在是「晨」
    assert runtime.align_clock_to_act(c, st, 1) is not None
    assert (st.get("clock") or {}).get("slot") == 2, "虚构钟上的幕锚失效了"


def test_the_slot_never_runs_backwards_within_a_day():
    """双保险: 就算别处再把钟往回拨, 同一天里的时段也不许倒退。
    注释里早写明了危害 —— 到期的约定会在 open↔missed 之间来回翻面。"""
    st = _st(3, 2)                      # 第3天·夜
    runtime.guard_clock_forward(st, day=3, slot=1)   # 有人想拨回「午」
    assert (st["clock"]["day"], st["clock"]["slot"]) == (3, 2), "时段倒流了"


def test_a_new_day_may_start_at_dawn():
    """跨天当然可以从夜回到晨 —— 那是往前走, 不是倒流。"""
    st = _st(3, 2)
    runtime.guard_clock_forward(st, day=4, slot=0)
    assert (st["clock"]["day"], st["clock"]["slot"]) == (4, 0)
