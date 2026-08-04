# -*- coding: utf-8 -*-
"""✨ 金色瞬间改为玩家主动触发 (Yi 2026-08-04)。

原来的样子: 程序每回合摇一次骰 (tuning.golden_chance=4%, 冷却 10 回合), 中了就当场
写一段。喂给模型的上下文只有 said_this_turn[-4:] —— **本回合最后四句**。于是模型
根本不知道最近发生了什么, 写出来的东西又贵又空。Yi 的原话: 「即时生成金色瞬间质量
太差了，没有全部理解最近的对话」。

改法两条:
  1. 自动摇骰关掉 (golden_chance 缺省 0)。玩家自己挑时机点, 愿意花这笔 token。
  2. 玩家点的那一次喂【足】上下文: 从存档的 beats 里捞最近几十拍, 而不是四句。

这两条是一体的 —— 正因为不再是每回合白摇, 才付得起「认真读一遍最近的戏」的成本。
"""
import copy

import pytest

from app.engine import runtime

CONTENT = {"story": {"id": "s", "characters": [
    {"id": "a", "name": "甲", "is_lead": True, "persona_text": "沉默寡言"},
    {"id": "b", "name": "乙", "persona_text": "话痨"}],
    "acts": [{"index": 1, "title": "一"}], "locations": []}}


class SpyLLM:
    """记下每次调用的 prompt, 好断言"上下文到底喂了什么"。"""

    def __init__(self):
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        if prompt.get("golden_moment"):
            return {"title": "绿宝与板车", "text": "他忽然停下脚步，把伞往你这边偏了偏。"}
        if prompt.get("risk_judge"):
            return {"risk": 100}
        return {"beats": [{"type": "dialogue", "speaker_name": "甲", "text": "嗯。"}],
                "affinity_delta": 0, "advance_act": False, "ending": None}

    def golden_prompts(self):
        return [p for p in self.prompts if p.get("golden_moment")]


def _st():
    st = runtime.default_state()
    st["rel"] = {"a": {"closeness": 30, "romance": 20}, "b": {"closeness": 5, "romance": 0}}
    return st


# ── 🎲 自动摇骰关掉 ─────────────────────────────────────────────────────────
def test_auto_roll_is_off_by_default():
    assert runtime.DEFAULT_TUNING["golden_chance"] == 0, \
        "自动摇骰还开着 — 玩家会继续收到那些没读懂上下文的金色瞬间"


def test_a_normal_turn_never_spits_out_a_golden_moment():
    """跑一串回合, 一次都不许自己冒出来 (原来是 4% 每回合)。"""
    llm = SpyLLM()
    c, st = copy.deepcopy(CONTENT), _st()
    for _ in range(30):
        st = runtime.run_turn(c, st, {"name": "我"}, "我们聊聊",
                              channel="say", llm=llm)["state"]
    assert not llm.golden_prompts(), "回合里自己摇出了金色瞬间"
    assert not [e for e in (st.get("album") or []) if e.get("kind") == "golden"]


# ── ✨ 玩家主动点的那一次 ───────────────────────────────────────────────────
RECENT = [{"speaker": "甲", "text": f"第{i}句，关于那把伞的事。"} for i in range(1, 25)]


def test_player_can_ask_for_one():
    llm = SpyLLM()
    c, st = copy.deepcopy(CONTENT), _st()
    got = runtime.golden_moment_now(c, st, llm, RECENT)
    assert got and got.get("text"), f"点了没出东西: {got}"
    assert got.get("title") == "绿宝与板车"


def test_the_prompt_actually_carries_the_recent_conversation():
    """质量问题的根子就在这 —— 原来只喂本回合最后 4 句。"""
    llm = SpyLLM()
    c, st = copy.deepcopy(CONTENT), _st()
    runtime.golden_moment_now(c, st, llm, RECENT)
    p = llm.golden_prompts()[0]
    fed = p.get("recent") or []
    assert len(fed) >= 12, f"只喂了 {len(fed)} 句 — 还是读不懂最近的戏"
    assert any("第1句" in (x.get("text") or "") for x in fed) or len(fed) >= 20, \
        "喂的窗口太靠后, 早先的铺垫全丢了"


def test_red_sample_four_lines_would_be_caught():
    """红样本: 旧的 said_this_turn[-4:] 只有四句, 这条断言确实会报红。"""
    old = RECENT[-4:]
    assert len(old) < 12, "红样本本身就该不达标, 否则上面那条是空转"


def test_it_picks_the_closest_character():
    llm = SpyLLM()
    c, st = copy.deepcopy(CONTENT), _st()
    runtime.golden_moment_now(c, st, llm, RECENT)
    assert llm.golden_prompts()[0]["char"]["name"] == "甲", "没挑最亲近的那个"


def test_it_lands_in_the_album_and_moves_the_relationship():
    llm = SpyLLM()
    c, st = copy.deepcopy(CONTENT), _st()
    before = int((st["rel"]["a"] or {}).get("closeness", 0))
    runtime.golden_moment_now(c, st, llm, RECENT)
    gold = [e for e in (st.get("album") or []) if e.get("kind") == "golden"]
    assert gold, "没进回忆册"
    assert gold[0]["title"] == "绿宝与板车"
    assert int(st["rel"]["a"]["closeness"]) > before, "关系没动"


def test_cooldown_stops_spamming_an_expensive_call():
    """这一下是真花钱的 —— 连点必须挡住。"""
    llm = SpyLLM()
    c, st = copy.deepcopy(CONTENT), _st()
    assert runtime.golden_moment_now(c, st, llm, RECENT)
    assert runtime.golden_moment_now(c, st, llm, RECENT) is None, "连点没挡住"
    assert len(llm.golden_prompts()) == 1, "冷却期内还是把钱花出去了"


def test_cooldown_expires():
    llm = SpyLLM()
    c, st = copy.deepcopy(CONTENT), _st()
    runtime.golden_moment_now(c, st, llm, RECENT)
    st["golden_cd"] = 0
    assert runtime.golden_moment_now(c, st, llm, RECENT), "冷却过了还不让点"


def test_a_dead_run_gets_nothing():
    llm = SpyLLM()
    c, st = copy.deepcopy(CONTENT), _st()
    st["ended"] = True
    assert runtime.golden_moment_now(c, st, llm, RECENT) is None


def test_an_empty_model_answer_costs_no_cooldown():
    """模型哑火不该把玩家的冷却烧掉 —— 那等于收了钱不给货。"""
    class Mute:
        def generate(self, prompt):
            return {}
    c, st = copy.deepcopy(CONTENT), _st()
    assert runtime.golden_moment_now(c, st, Mute(), RECENT) is None
    assert int(st.get("golden_cd") or 0) == 0, "哑火还扣了冷却"


def test_title_stays_clean_of_nested_brackets():
    """老实弹: 模型自带的括号会跟外层「」套娃 → ✨「【绿宝与板车轮声】」"""
    class Bracketed:
        def generate(self, prompt):
            return {"title": "【绿宝与板车】", "text": "他把伞偏了偏。"}
    c, st = copy.deepcopy(CONTENT), _st()
    got = runtime.golden_moment_now(c, st, Bracketed(), RECENT)
    assert got["title"] == "绿宝与板车", f"标题没消毒: {got['title']!r}"
