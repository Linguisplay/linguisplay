# -*- coding: utf-8 -*-
"""🪞 被说中的那一下才叫被看见 (Yi 2026-08-08:「要像心理医生一样分析了解玩家」)。

现状: 引擎确实在建玩家档案, 也确实把「这个角色对你的印象」喂给了演员。但喂的时候
带一句 ——「自然流露在态度里，【不要复述它】」。

那句 craft 上是对的 (复读摘要很蠢), 但它同时保证了【玩家永远感觉不到被看见】:
角色心里有你的画像, 一个字都不许说出来。

心理医生的那一下恰恰是【说出口】—— 不是分析报告, 是在你露出跟它对得上、或正相反
的一面时, 短短点破一句。所以规则要说清【什么时候该说】, 而不只是「别说」。

⚠️ 顺带记一笔查出来的东西: 全局事实是【跨局】带着走的 (同一个玩家 5 局, 每局
facts=6, 连没玩过一拍的那局也有), 而每个角色对玩家的印象【每开一局清零】——
而演员唯一读得到的正是后者。要不要让角色跨局记得玩家, 是产品决定不是 bug,
记在这里等 Yi 拍。
"""
from app.engine import qwen


def _sys(**kw):
    p = {"speaker_name": "甲", "speaker_persona": "x", "channel": "say",
         "persona": {"name": "我"}, "context": {}}
    p.update(kw)
    return qwen._build_system(p)


def test_the_impression_is_a_basis_for_judgement_not_a_line_to_recite():
    s = _sys(player_read="嘴上说不在乎，其实每次都第一个到")
    assert "嘴上说不在乎" in s
    assert "复述" in s or "复读" in s, "还得拦住它把印象当台词念出来"


def test_it_is_told_when_to_say_it_out_loud():
    """⚠️ 这一条是这一刀的全部意义。只说「别复述」= 玩家永远感觉不到被看见。"""
    s = _sys(player_read="嘴上说不在乎，其实每次都第一个到")
    assert "点破" in s, "没告诉它什么时候该把看出来的说出口"
    assert "正相反" in s or "对不上" in s, "没说【印象被印证或被推翻】才是那个时机"


def test_it_is_told_to_keep_it_short_and_unexplained():
    s = _sys(player_read="x")
    assert "别解释" in s and "别说教" in s, "说出口容易变成分析报告，那比不说更糟"


def test_being_wrong_is_allowed():
    """看错了要能被纠正 —— 否则它会为了自圆其说而扭曲玩家。"""
    s = _sys(player_read="x")
    assert "纠正" in s


def test_no_impression_no_block():
    assert "点破" not in _sys()
