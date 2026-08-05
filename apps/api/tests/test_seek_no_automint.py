# -*- coding: utf-8 -*-
"""🔎 找人不再自动造真, 该不该有这个人交给导演判断 (Yi 2026-08-05)。

原来的样子: 玩家提到一个册子上没有的名字 → 引擎先额外调一次 `scout_char` 判官问
「这名字属不属于本世界观」→ 判官说属于就【当场造真】: 角色入册、铸一块地、钉住行踪,
整个回合短路成一张「TA此刻在 X，去吗？」的确认片。

问题: 判断权被拿走了。判官只看名字和世界观梗概, 看不见这一场的戏、看不见玩家为什么
提这个名字, 于是玩家随口一句就凭空多出一个人。而导演本来就有 new_character 字段,
它读得到整场上下文, 才是该拍板的那个。

改法: 关掉 scout+自动造真 (省一次 LLM 调用), 把名字原样递给导演, 并把指令从「必须
让搜寻落地」改成【你来判断这个世界里该不该有这号人】—— 该有就用 new_character 让 TA
真登场, 不该有就在世界观内如实否认并指条路。
"""
import copy

import pytest

from app.engine import runtime

STORY = {"story": {"id": "s", "sandbox": {"enabled": True},
                   "title": "旧巷", "world_facts": "南方小城，雨季很长。",
                   "characters": [{"id": "a", "name": "甲", "is_lead": True}],
                   "acts": [{"index": 1, "title": "一"}],
                   "locations": [{"id": "l1", "name": "旧巷", "detail": "x", "exits": []}]}}


# ⚠️ 用「我找沈青梧」而不是「我去打听打听…」: seek_unknown 的抽取器挺挑, 后者根本
#    抽不出名字, 整条路走不到, 测试会静静空转 (顺带记一笔: 「有人见过沈青梧吗」会抽出
#    残句「过沈青梧吗」—— 那是抽取器的老毛病, 交给导演判断后至少不会拿它当人名了)。
class SeekLLM:
    """记下每次调用, 好断言【判官那一次调用没发生】。"""

    def __init__(self, new_char=""):
        self.prompts = []
        self.new_char = new_char

    def generate(self, prompt):
        self.prompts.append(prompt)
        if prompt.get("scout_char"):
            return {"fits": True, "who": "码头的老熟人", "where": "码头",
                    "persona": "寡言", "voice": "半句话"}
        if prompt.get("describe_place"):
            return {"name": "码头", "detail": "水汽"}
        if prompt.get("risk_judge"):
            return {"risk": 100}
        out = {"beats": [{"type": "dialogue", "speaker_name": "甲", "text": "没听过这号人。"}],
               "affinity_delta": 0, "advance_act": False, "ending": None}
        if prompt.get("group_mode") in ("primary", None) and self.new_char:
            out["new_char"] = self.new_char
        return out

    def scout_calls(self):
        return [p for p in self.prompts if p.get("scout_char")]

    def primary(self):
        # ⚠️ 别写成 `p.get("group_mode") in ("primary", None)` —— 那会把【压根没有这个键】
        #    的辅助调用 (risk_judge 之类) 也算成主拍, next() 抓到第 0 条就返回, 于是断言
        #    看到 seek_unknown=None, 冤枉产品 (实弹: 名字其实好好地送到了导演手里)。
        #    认 can_new_char 这个主拍独有的键最稳。抓不到东西先怀疑抓法。
        return next((p for p in self.prompts if "can_new_char" in p), None)


def _st():
    st = runtime.default_state()
    st["location_id"] = "l1"
    return st


def _names(content):
    return [c.get("name") for c in (content.get("story") or {}).get("characters") or []]


# ── 🔒 开关 ─────────────────────────────────────────────────────────────────
def test_auto_mint_is_off_by_default():
    assert runtime.SEEK_AUTO_MINT is False, \
        "找人自动造真还开着 — 玩家随口一个名字就会凭空多出一个人"


# ── 🚫 不再自动造人 ─────────────────────────────────────────────────────────
def test_an_unknown_name_does_not_mint_anybody():
    llm = SeekLLM()
    c, st = copy.deepcopy(STORY), _st()
    before = _names(c)
    runtime.run_turn(c, st, {"name": "我"}, "我找沈青梧",
                     channel="say", llm=llm)
    assert _names(c) == before, f"凭空造出了人: {set(_names(c)) - set(before)}"


def test_the_extra_scout_call_is_gone():
    """判官那一次调用是白花的钱 —— 判断权交给导演之后就不该再打了。"""
    llm = SeekLLM()
    c, st = copy.deepcopy(STORY), _st()
    runtime.run_turn(c, st, {"name": "我"}, "我找沈青梧",
                     channel="say", llm=llm)
    assert not llm.scout_calls(), "还在调 scout_char 判官"


def test_the_turn_is_not_short_circuited_into_a_seek_chip():
    """原来会直接吐一张「TA在X，去吗？」的确认片, 整场戏都不演了。"""
    llm = SeekLLM()
    c, st = copy.deepcopy(STORY), _st()
    out = runtime.run_turn(c, st, {"name": "我"}, "我找沈青梧",
                           channel="say", llm=llm)
    mr = out.get("move_request") or {}
    assert not mr.get("seek"), f"还是短路成了找人确认片: {mr}"
    assert out.get("beats"), "这一回合连戏都没演"


# ── 🎬 判断权交回导演 ───────────────────────────────────────────────────────
def test_the_director_is_handed_the_name():
    llm = SeekLLM()
    c, st = copy.deepcopy(STORY), _st()
    runtime.run_turn(c, st, {"name": "我"}, "我找沈青梧",
                     channel="say", llm=llm)
    p = llm.primary()
    assert p is not None, "没找到主拍的 prompt"
    assert (p.get("seek_unknown") or "") == "沈青梧", \
        f"导演没拿到这个名字: {p.get('seek_unknown')!r}"


def test_the_director_is_asked_to_judge_not_ordered_to_deliver():
    """指令的措辞要从「必须让搜寻落地」变成「你来判断该不该有这号人」。"""
    from app.engine.qwen import _seek_directive
    d = _seek_directive("沈青梧", sandbox=True, en=False)
    assert d, "没有生成指令"
    assert "判断" in d, f"指令里没让导演判断: {d}"
    assert "new_character" in d, "没告诉导演该有的话怎么让人登场"
    assert "没有" in d or "不认识" in d or "否认" in d, "没给「不该有」的出路"


def test_the_director_can_still_bring_the_person_in():
    """判断权交回去了, 但通路要还在 —— 导演说该有, 人就得真出来。"""
    llm = SeekLLM(new_char="沈青梧｜码头上的老熟人，左手总揣在兜里｜说半句留半句")
    c, st = copy.deepcopy(STORY), _st()
    runtime.run_turn(c, st, {"name": "我"}, "我找沈青梧",
                     channel="say", llm=llm)
    assert "沈青梧" in _names(c), "导演批了却没造出人来"
    born = next(x for x in c["story"]["characters"] if x.get("name") == "沈青梧")
    assert born.get("generated") is True
    assert "左手" in (born.get("persona_text") or ""), "人设没带上"
    assert "半句" in (born.get("voice_print") or ""), "说话规律没带上"


# ── 🧪 红样本自验 ───────────────────────────────────────────────────────────
def test_red_sample_the_old_directive_ordered_delivery():
    """修复前的措辞是「这一拍必须给出实在的下文，三选一」—— 那是命令不是判断。"""
    before = "【打听要有着落】…这一拍必须给出实在的下文，三选一：①在场者给出确凿线索"
    assert "判断" not in before, "红样本本身就该不含「判断」, 否则上面那条是空转"
