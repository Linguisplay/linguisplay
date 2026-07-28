# -*- coding: utf-8 -*-
"""🔥 床戏阶梯误伤回归 (Yi 2026-07-28 实弹)。

实弹: 玩家第二句话「（刚一拐进巷口，就撞上他的视线）发生什么了」命中第4级的
(干|操|上)(她|他|我|你)，一步把阶梯从 0 推到「已经交合、正在体内」，此后整局每拍
都在吃一份床戏深锚。全库 4582 拍扫描: 19 个有热度的档里 18 个正文没有性内容。
下面每一条都是从生产库里捞出来的真句子。"""
from app.engine import heat


def _climb(text, from_model=False, start=0, loc="l1"):
    st = {"heat": {"stage": start, "at": loc}}
    heat.advance(st, text, loc, from_model=from_model)
    return st["heat"]["stage"]


# ── ① 从 0 起, 这些真句子一级都不许推 ──────────────────────────

FALSE_POSITIVES_PLAYER = [
    "（刚一拐进巷口，就撞上他的视线，我顿了顿开口）发生什么了",   # ← 实弹原句
    "我迈步跟上她的速度，与她并肩而行",
    "燕赤霞对上你的目光，那张被风沙磨粗的黑脸没什么表情",
    "油星溅到围裙上他也不管",
    "你的唇撞上我的，不轻不重",
]
FALSE_POSITIVES_MODEL = [
    "远处天焚炼气塔顶端的火苗舔舐着夜幕",
    "煤气灯在头顶吞吐着昏黄的光晕",
    "她眼角还泛着潮红，目光却直直撞进你眼里。",
    "街灯微弱的光芒透过磨砂玻璃投射进来",
    "一个禁军的全息投影被投射了出来",
    "他把线头对准凹槽，没插进去，只是悬在接口上方",
    "You came to sell the last of your grain.",
]


def test_player_false_positives_do_not_ignite():
    for t in FALSE_POSITIVES_PLAYER:
        assert _climb(t) == 0, t


def test_model_false_positives_do_not_ignite():
    for t in FALSE_POSITIVES_MODEL:
        assert _climb(t, from_model=True) == 0, t


# ── ② 真的性内容仍然要认 (别修过头) ────────────────────────────

def test_real_intimacy_still_detected():
    assert _climb("我吻上她的唇", start=0) == 1
    assert _climb("脱掉她的衬衫", start=0) >= 1
    assert _climb("插进她的身体", start=3) == 4          # 逐级到位
    assert _climb("高潮了", start=4) == 5


# ── ③ 补火同样不许被误伤点着 ───────────────────────────────

def test_catchup_not_ignited_by_false_positive():
    st = {"heat": {"stage": 0, "at": "l1"}}
    heat.catchup(st, ["他撞上她的目光，愣了一下。", "巷口传来收档的声音。"], "l1")
    assert st["heat"]["stage"] == 0


# ── ⑤ 反向自愈: 账本比正文烫就降温 (存量误判档自己下得来) ────────

def test_cool_down_when_prose_has_no_evidence():
    st = {"heat": {"stage": 4, "at": "l1"}}
    got = heat.cool_if_unsupported(st, ["他靠在墙边，点了根烟。", "巷口传来收档的声音。"])
    assert got == 1 and st["heat"]["stage"] == 1


def test_cool_keeps_real_scene_hot():
    st = {"heat": {"stage": 4, "at": "l1"}}
    got = heat.cool_if_unsupported(st, ["他挺进她的身体，节奏乱了。"])
    assert got == 4 and st["heat"]["stage"] == 4
