# -*- coding: utf-8 -*-
"""🗣 历史里的示范必须长得跟要求的输出一样 (Yi 报障 2026-08-07:「角色现在不能发言了」)。

生产实况: 8/6 角色台词占比 52%, 8/7 掉到 13%。查下来是个【自我强化的污染回路】:

  ① 某一拍模型忘了打行首前缀 → 分行器认不出台词, 整坨落成一条 description
  ② 那条【不带前缀】的 description 进了历史, 成了模型「我平时这么写」的示范
  ③ 下一拍更不打前缀 → 又落成 description → 回到 ①

根因在 history_for: dialogue 进历史时【贴了】说话人前缀 (「蓝信一：…」),
而 description 【不贴】。于是历史里正确示范与污染示范混在一起, 而输出协议
(_LineSegmenter) 要的是每一行都有前缀:「旁白：…」/「名字：…」。

2026-08-06 我把逐字窗口从 14 抬到 24, 等于把污染示范一次加了 70% —— 回路的增益
被我拧大了, 当天就跑飞。窗口本身没错, 错的是历史里的示范跟输出格式对不上。

修法: 旁白进历史时贴上协议自己的记号「旁白：」。原注释担心「贴了模型会学着把旁白
写成台词」—— 那说的是贴【角色名】; 「旁白」是 _LineSegmenter 保留的叙述者记号,
它会被映射回 narration, 不会串。
"""
from app.engine import qwen, runtime


BEATS = [
    {"author": "player", "type": "dialogue", "text": "你还好吗？", "present_ids": None},
    {"author": "engine", "type": "description", "present_ids": None,
     "text": "抹掉嘴角的血迹，歪头看你一眼。"},
    {"author": "engine", "type": "dialogue", "speaker_name": "蓝信一",
     "text": "小伤。蔡sir，这么晚还巡巷子？", "present_ids": None},
]


def _h():
    return runtime.history_for(BEATS, "a")


# ── 历史里的每一条都要能被输出协议认出来 ────────────────────────────────────────

def test_narration_carries_the_narrator_prefix():
    """不贴前缀的旁白就是污染示范 —— 模型照着它写, 台词也不打前缀了。"""
    narr = [m for m in _h() if "抹掉嘴角" in m["content"]][0]
    assert narr["content"].startswith("旁白："), \
        f"旁白进历史时没贴协议记号: {narr['content'][:30]!r}"


def test_dialogue_still_carries_the_speaker():
    """这条本来就是对的, 别在修旁白时把它碰坏。"""
    d = [m for m in _h() if "小伤" in m["content"]][0]
    assert d["content"].startswith("蓝信一："), d["content"][:30]


def test_every_assistant_line_is_parseable():
    """真正的合同: 历史里每一条助手消息, 都要能被 _LineSegmenter 认出身份。
    认不出的那条, 就是在教模型写出认不出的东西。"""
    import re
    pref = qwen._line_prefix_re()
    for m in _h():
        if m["role"] != "assistant":
            continue
        assert pref.match(m["content"]), f"这条历史示范没有身份前缀: {m['content'][:36]!r}"


def test_the_narrator_token_maps_back_to_narration():
    """贴上去的记号必须被分行器认回旁白, 不能变成一个叫「旁白」的角色。"""
    seg = qwen._LineSegmenter("蓝信一")
    out = seg.feed("旁白：他退了半步。\n")
    kinds = {k for k, who, t in out if t.strip()}
    assert "narration" in kinds, out
    assert not any(who == "旁白" for k, who, t in out), f"「旁白」被当成角色了: {out}"


def test_player_lines_are_untouched():
    u = [m for m in _h() if m["role"] == "user"][0]
    assert u["content"] == "你还好吗？"


# ── 认知边界不许被这一刀碰松 ──────────────────────────────────────────────────

def test_the_witness_gate_still_holds():
    beats = [{"author": "engine", "type": "description", "text": "只有甲看见的雨",
              "present_ids": ["a"]}]
    assert runtime.history_for(beats, "a")
    assert not runtime.history_for(beats, "b"), "不在场的人拿到了不该有的旁白"


def test_blank_narration_is_dropped():
    beats = [{"author": "engine", "type": "description", "text": "   ", "present_ids": None}]
    assert runtime.history_for(beats, "a") == []


# ── 🔭 遥测: 这件事不许再无声烂掉 ──────────────────────────────────────────────

def test_a_speechless_turn_is_countable():
    """被直接搭话却一句台词都没有 —— 那正是这次报障的现场。
    没有读口就只能等玩家来骂, 而这次就是等来的。"""
    beats = [{"author": "engine", "type": "description", "text": "他看了你一眼。"}]
    assert runtime.speechless_turn(beats, channel="say") is True
    beats2 = beats + [{"author": "engine", "type": "dialogue",
                       "speaker_name": "蓝信一", "text": "嗯。"}]
    assert runtime.speechless_turn(beats2, channel="say") is False


def test_an_action_turn_is_allowed_to_be_silent():
    """玩家只是做了个动作, 角色不吭声是合法的, 不许误报。"""
    beats = [{"author": "engine", "type": "description", "text": "他看了你一眼。"}]
    assert runtime.speechless_turn(beats, channel="do") is False
