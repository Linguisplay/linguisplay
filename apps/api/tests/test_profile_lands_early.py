# -*- coding: utf-8 -*-
"""🪞 档案要在玩家还在的时候建起来 (Yi 反复强调:「收集玩家信息建 profile 再对症下药」)。

线上实测把这条钉死了:
    DISTILL_EVERY = 8   玩家第 8 个回合才第一次蒸馏
    而一局的玩家回合数【中位是 4】(133 局里 69 局活不过 4 拍)
  ⇒ 一半以上的玩家，在档案系统第一次运行之前就已经离开了。

结果: 184 局里只有 23 局有【每个角色自己对玩家的印象】, 而那正是演员唯一读得到的
那一份 (player_read)。全局事实有 70 局, 但它只喂导演, 不喂演员 —— 这是对的,
因为全局事实会越过见证边界。

所以修法不是「把全局事实也给演员」(那会拆护城河), 是【让第一次蒸馏落在玩家还在的
窗口里】: 头一次早点来, 之后照旧稀疏。
"""
from app.engine import profile


def test_the_first_read_lands_inside_the_median_run():
    """中位一局只有 4 拍 —— 第一次蒸馏必须在那之前。"""
    st = {}
    fires = [i + 1 for i in range(6) if profile.note_turn(st)]
    assert fires and fires[0] <= 3, f"第一次蒸馏在第 {fires[0] if fires else '∞'} 拍，玩家早走了"


def test_it_does_not_fire_every_single_turn():
    """别把便宜调用变成每拍一次 —— 那是另一种浪费。"""
    st = {}
    fires = sum(1 for _ in range(20) if profile.note_turn(st))
    assert fires <= 6, f"20 拍里蒸了 {fires} 次，太密"


def test_long_runs_still_get_refreshed():
    st = {}
    fires = [i + 1 for i in range(30) if profile.note_turn(st)]
    assert len(fires) >= 4, "长局里档案不再更新了"
