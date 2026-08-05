# -*- coding: utf-8 -*-
"""🔁 独角戏的旁白循环 (Yi 2026-08-05 玩家报障:「到了新场景独自一人的时候旁白会循环」)。

病根是【覆盖漏洞】, 不是缺功能: 治复读的场账本在这条路上根本开不了。
它的开场条件要「玩家真发言 + 有引擎台词拍落地 + 有别人在场」, 独自一人时后两条
同时不成立 → 场开不了 → spent 不落账 → 那句「本场已经演过…换个措辞也不行」
永远进不了 observe 那条路的提示词。

而独角戏恰恰是全引擎最容易打转的地方: 没有对话对象推着走, 模型只能反复描述同一个
房间。补法是把【已经在存的】近拍旁白档 _recent_narr 喂进去 —— 零新状态零新调用。
"""
from app.engine import qwen


def _obs(recent=None, **kw):
    p = {"observe": True, "persona": {"name": "我"}, "language": "zh",
         "place": "客栈天字一号房", "cast": [], **kw}
    if recent is not None:
        p["recent_narr"] = recent
    return qwen._build_observe_system(p)


def test_a_solo_beat_is_told_what_it_just_wrote():
    got = _obs(["窗外的雨敲在瓦上，一声一声。桌上的茶凉了。"])
    assert "【你刚写过这些·不许重来】" in got
    assert "窗外的雨敲在瓦上" in got
    assert "换个措辞再写一遍也不行" in got, \
        "复读是【换措辞】演同一个画面, 不是逐字重复 — 这半句是关键"


def test_it_also_says_what_to_do_instead():
    """只说「别重复」会逼出更空的句子。必须给出往前走的三条出路。"""
    got = _obs(["雨敲在瓦上。"])
    assert "新的、之前没提过的" in got
    assert "宁可短" in got, "写不出新东西时的出路 — 少了它模型会硬凑"


def test_nothing_is_added_when_there_is_no_history():
    """新档第一拍没有近拍档 — 提示词必须与从前逐字相同。"""
    for empty in (None, [], ["", "   "]):
        assert "【你刚写过这些" not in _obs(empty)


def test_only_the_last_two_are_sent():
    """近拍档存三条, 但这里只送两条 —— 它每一拍都进提示词, 三条是白烧。"""
    got = _obs(["第一拍甲乙丙", "第二拍丁戊己", "第三拍庚辛壬"])
    assert "第一拍甲乙丙" in got and "第二拍丁戊己" in got
    assert "第三拍庚辛壬" not in got


def test_each_excerpt_is_capped():
    """一拍旁白可以很长 (存的是 1200 字)。整段灌进去每一拍都在烧。"""
    got = _obs(["雨" * 900])
    assert got.count("雨") <= 420, "近拍档没截断"


# ── 年代也走这条路 (Step 5 漏了 observe) ──────────────────────────────────
def test_the_era_reaches_the_solo_path_too():
    """独自一人时, 到达旁白与打量全归 observe 写。它拿不到年代, 1899 的档里
    走进一个新地点就会冒出挂钟和玻璃门。"""
    got = _obs(["雨敲在瓦上。"], era="1899年，清末", device="传讯符")
    assert "1899年，清末" in got
    assert "绝不许因为年代而拒绝使用它" in got, "手机豁免也得跟到这条路上"


def test_a_story_with_no_era_keeps_the_solo_prompt_byte_identical():
    a = _obs(["雨敲在瓦上。"])
    b = _obs(["雨敲在瓦上。"], era="", device="手机")
    assert a == b, "没设年代的本子, 这条路的提示词必须一个字不变"


# ── 在场铁律没被挤掉 ──────────────────────────────────────────────────────
def test_the_empty_room_law_is_still_there():
    """独自一人这条路上最要紧的既有铁律 — 新加的块不许把它挤走或压过。"""
    got = _obs(["雨敲在瓦上。"])
    assert "没有任何人（只有玩家自己）" in got
    assert "绝不允许凭空召来一个人替你作答" in got
