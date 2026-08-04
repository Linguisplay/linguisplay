# -*- coding: utf-8 -*-
"""🪃 回扣旧事的【素材】与【验真】(2026-08-04 实弹):

生产 166 局实测: 回调注入 166 次, 验真通过 3~5 次 = 约 2% 成功率。两个病因:
  ① 素材池 278 条里 193 条(69%)是 meet「初次见面」, 而取料取 fresh[0] = 最老那条,
     所以角色第一次回扣旧事说的几乎必然是「我们第一次见面」—— 这不是回忆是寒暄。
  ② 验真要求模型自报的摘录【前 12 字原样】出现在本轮正文里, 模型换个说法就判失败
     (blanks 累计 42, 单局最高连续 14 次)。

同时 album(时刻卡)是引擎判定的高光 + LLM 精写好的文本, 生产 33 张, 却从不进任何
提示词 —— 全仓最贵的浪费, 这里把它接成第一素材池。
"""
from app.engine import runtime


CID = "c1"


def _state(**kw):
    st = runtime.default_state()
    st.update(kw)
    return st


def test_meet_is_not_callback_material_when_anything_else_exists():
    """「初次见面」是寒暄不是回忆 —— 有别的旧事时绝不能取它。"""
    st = _state(rel_log={CID: [
        {"act": 1, "kind": "meet", "text": "初次见面，在训练场"},
        {"act": 1, "kind": "reveal", "text": "他说漏了嘴：那把刀是他爹留的"},
        {"act": 2, "kind": "golden", "text": "「接住硬币」：你伸手，他没躲"},
    ]})
    mat = runtime.pick_callback_material({}, st, CID)
    assert mat and "初次见面" not in mat, f"取到了寒暄而不是旧事: {mat!r}"


def test_meet_is_still_usable_as_the_last_resort():
    """只有初见时不能空手 —— 宁可寒暄也别没有素材。"""
    st = _state(rel_log={CID: [
        {"act": 1, "kind": "meet", "text": "初次见面，在训练场"},
        {"act": 1, "kind": "meet", "text": "第二次照面，在食堂"},
    ]})
    assert runtime.pick_callback_material({}, st, CID), "没有别的旧事时也不该空手"


def test_album_moments_feed_the_callback():
    """33 张时刻卡是精写好的高光, 必须能被角色重提。"""
    st = _state(album=[{"kind": "golden", "title": "灯下那一句",
                        "text": "她说这话时没看你，可你听见了。",
                        "char_id": CID, "name": "阿珍"}])
    mat = runtime.pick_callback_material({}, st, CID)
    assert "灯下那一句" in mat or "没看你" in mat, f"时刻卡没进素材池: {mat!r}"


def test_album_of_another_character_is_not_mine():
    """认知边界: 别人的名场面不能变成我的回忆。"""
    st = _state(album=[{"kind": "golden", "title": "别人的高光", "text": "与你无关的一幕",
                        "char_id": "other", "name": "别人"}])
    assert not runtime.pick_callback_material({}, st, CID)


def test_callback_lands_when_the_model_paraphrases():
    """验真放宽: 模型把旧事换个说法织进正文, 也算落地。"""
    mat = "「接住硬币」：你伸手，他没躲"
    turn = "“上次你伸手接硬币那回，”他忽然开口，“我其实吓了一跳。”"
    assert runtime._callback_landed(mat, "上次你伸手接硬币", turn)


def test_callback_still_rejects_a_bare_claim():
    """但空口报审仍要判失败 —— 否则计时器被白白重置, 回调再也不来。"""
    mat = "「接住硬币」：你伸手，他没躲"
    turn = "“嗯。”他点了点头，没再说什么。"
    assert not runtime._callback_landed(mat, "我提了接住硬币那件事", turn)
