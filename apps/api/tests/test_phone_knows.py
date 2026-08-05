# -*- coding: utf-8 -*-
"""🧠 TA 记得你说过的【具体的事】 (Yi 2026-08-05 三刀之 P2)。

Yi 的原话:「角色在手机上的互动和记忆非常重要，这部分现在太落后了」。互动那两刀
(时机/形状) 已落地; 这一刀治记忆。

现状盘点 —— 已经有两本账, 但都答不上这件事:
  · profile.facts    跨角色的玩家习惯, 合同里明写【不进对白】(角色不开上帝视角)
  · profile.by_char  每个角色相处出的印象, 但只有 60 字的"感觉"(「嘴硬心软」),
                     不是具体的事
  · memory_by_char   滚动散文摘要 —— 每蒸馏一次就更概括一层, 具体细节必然褪色
缺的是: TA 亲耳听你说过的、可以在三天后原样搬出来的那一件小事(「你不是说不吃香菜」)。

设计要点:
  · 一本【按角色分】的事实账 state["knows"][cid] —— 认知有边界, 不许开天眼:
    只有这个角色亲身经历的对话才进 TA 那一本。
  · 搭在已有的 summarize 调用上抽取, **零新增 LLM 调用** (本仓对成本很在意)。
  · 去重 + 封顶 —— 不然聊得越久提示词越肥, 而肥了模型反而抓不住重点。
  · 事实是【长记性】的: 摘要可以越滚越概括, 这本账不许被概括掉。
"""
import copy

import pytest

from app.engine import runtime


def _st():
    st = runtime.default_state()
    st["met_ids"] = ["b"]
    return st


# ── 📒 账本本身 ────────────────────────────────────────────────────────────
def test_a_fact_lands_under_the_character_who_heard_it():
    st = _st()
    runtime.knows_add(st, "b", ["不吃香菜", "妹妹在城南读书"])
    assert runtime.knows_of(st, "b") == ["不吃香菜", "妹妹在城南读书"]


def test_knowledge_has_a_boundary_between_characters():
    """认知边界是本仓的法条: 你只对乙说过的事, 丙不许知道。"""
    st = _st()
    runtime.knows_add(st, "b", ["不吃香菜"])
    assert runtime.knows_of(st, "z") == [], "一个角色的记忆漏进了另一个角色"


def test_the_same_fact_twice_does_not_double_up():
    st = _st()
    runtime.knows_add(st, "b", ["不吃香菜"])
    runtime.knows_add(st, "b", ["不吃香菜", "  不吃香菜  "])
    assert runtime.knows_of(st, "b") == ["不吃香菜"]


def test_near_duplicates_do_not_pile_up():
    """模型每次换个说法就存一条的话, 三天后这本账就没法看了。"""
    st = _st()
    runtime.knows_add(st, "b", ["他不吃香菜"])
    runtime.knows_add(st, "b", ["不吃香菜"])
    assert len(runtime.knows_of(st, "b")) == 1, \
        f"近似重复没合并: {runtime.knows_of(st, 'b')}"


def test_the_ledger_is_capped_newest_wins():
    st = _st()
    runtime.knows_add(st, "b", [f"第{i}件事" for i in range(40)])
    got = runtime.knows_of(st, "b")
    assert len(got) <= runtime.KNOWS_CAP, f"没封顶: {len(got)} 条"
    assert "第39件事" in got, "封顶时把最新的挤掉了"


def test_blanks_and_junk_are_refused():
    st = _st()
    runtime.knows_add(st, "b", ["", "   ", None, "无", "x" * 200])
    got = runtime.knows_of(st, "b")
    assert all(g.strip() and g != "无" for g in got), f"垃圾进账了: {got}"
    assert all(len(g) <= 40 for g in got), "没截长"


# ── 🔌 接进蒸馏: 零新增 LLM 调用 ──────────────────────────────────────────
STORY = {"story": {"id": "s", "phone": {"enabled": True, "device": "手机"},
                   "tuning": {"turns_per_slot": 6},
                   "characters": [{"id": "a", "name": "甲", "is_lead": True},
                                  {"id": "b", "name": "乙"}],
                   "acts": [{"index": 1, "title": "一"}],
                   "locations": [{"id": "l1", "name": "旧巷", "detail": "x", "exits": []}]}}


class DigestLLM:
    def __init__(self):
        self.calls = []

    def generate(self, prompt):
        self.calls.append(prompt)
        if prompt.get("summarize"):
            return {"memory": "你们聊了很多。", "facts": ["不吃香菜", "怕打雷"]}
        if prompt.get("phone_reply"):
            return {"msgs": ["嗯。"], "closeness": 0, "romance": 0}
        return {}

    def summarize_calls(self):
        return [p for p in self.calls if p.get("summarize")]


def test_facts_ride_the_existing_summarize_call():
    st = _st()
    th = runtime._thread(st, "b")
    th["msgs"] = [{"from": "me" if i % 2 else "them", "text": f"第{i}句"}
                  for i in range(30)]
    llm = DigestLLM()
    runtime._digest_phone_overflow(st, "b", llm)
    assert len(llm.summarize_calls()) == 1, "多打了调用 — 成本涨了"
    assert runtime.knows_of(st, "b") == ["不吃香菜", "怕打雷"], \
        f"蒸馏出来的事实没入账: {runtime.knows_of(st, 'b')}"


def test_the_summarize_prompt_asks_for_facts():
    st = _st()
    th = runtime._thread(st, "b")
    th["msgs"] = [{"from": "me" if i % 2 else "them", "text": f"第{i}句"}
                  for i in range(30)]
    llm = DigestLLM()
    runtime._digest_phone_overflow(st, "b", llm)
    p = llm.summarize_calls()[0]
    assert p.get("want_facts"), "没让蒸馏顺手把事实抽出来"


# ── 💬 TA 真的会用上 ─────────────────────────────────────────────────────
def test_the_reply_prompt_carries_what_this_character_knows():
    c, st = copy.deepcopy(STORY), _st()
    st["contact_ids"] = ["b"]
    st["char_pins"] = {"b": "l1"}
    runtime.knows_add(st, "b", ["不吃香菜"])
    llm = DigestLLM()
    runtime.phone_send(c, st, {"name": "我"}, "b", "晚上吃什么", llm=llm)
    p = next(x for x in llm.calls if x.get("phone_reply"))
    assert "不吃香菜" in str(p.get("knows") or ""), \
        f"TA 记着的事没进提示词: {p.get('knows')}"


def test_a_stranger_character_carries_nothing():
    c, st = copy.deepcopy(STORY), _st()
    st["contact_ids"] = ["b"]
    runtime.knows_add(st, "z", ["不吃香菜"])   # 记在别人名下
    llm = DigestLLM()
    runtime.phone_send(c, st, {"name": "我"}, "b", "在吗", llm=llm)
    p = next(x for x in llm.calls if x.get("phone_reply"))
    assert not (p.get("knows") or []), "把别人的记忆喂给了乙 = 开天眼"


# ── 🧪 红样本自验 ────────────────────────────────────────────────────────
def test_red_sample_a_rolling_digest_loses_the_detail():
    """滚动摘要每蒸一次就概括一层 —— 这正是这本账要挡的事。"""
    prose = "你们聊了很多，关系有进展。"
    assert "香菜" not in prose, "红样本本身就该证明细节会被概括掉"


# ── 🔬 真正的解析器 (上面的桩绕过了它) ────────────────────────────────────
# 上面那些用例喂的是"模型直接返回 facts 字段"的桩 —— 那测不到【从散文里把「记住：」
# 那一行抠出来】的真实解析。这条走真解析器, 只把 HTTP 那一层换掉。
class _Resp:
    def __init__(self, text):
        self._t = text

    def json(self):
        return {"choices": [{"message": {"content": self._t}}]}


def _summarize_with(monkeypatch, text, want_facts=True):
    from app.engine import qwen
    monkeypatch.setattr(qwen, "_post_chat", lambda *a, **k: _Resp(text))
    q = qwen.QwenLLM.__new__(qwen.QwenLLM)
    q._url, q._key, q._summary_model = "u", "k", "m"
    return q._summarize({"summarize": True, "prior_memory": "旧的",
                         "new_lines": [{"role": "user", "content": "x"}],
                         "want_facts": want_facts})


def test_the_marker_line_is_parsed_into_facts(monkeypatch):
    out = _summarize_with(monkeypatch,
                          "- 关系有进展。\n- 他提到了家里的事。\n记住：不吃香菜；妹妹在城南读书；怕打雷")
    assert out["facts"] == ["不吃香菜", "妹妹在城南读书", "怕打雷"], out["facts"]


def test_the_marker_line_does_not_pollute_the_prose_digest(monkeypatch):
    out = _summarize_with(monkeypatch, "- 关系有进展。\n记住：不吃香菜")
    assert "记住" not in out["memory"], f"标记行漏进了散文摘要: {out['memory']!r}"
    assert "关系有进展" in out["memory"]


def test_nothing_worth_remembering_is_honored(monkeypatch):
    out = _summarize_with(monkeypatch, "- 闲聊。\n记住：无")
    assert out["facts"] == []
    assert "记住" not in out["memory"]


def test_a_model_that_forgets_the_marker_still_gives_a_digest(monkeypatch):
    """模型不写那一行也不能炸 —— 摘要照旧, 事实这轮空手。"""
    out = _summarize_with(monkeypatch, "- 就是聊了聊。")
    assert out["memory"] == "- 就是聊了聊。"
    assert out["facts"] == []


def test_facts_are_capped_and_trimmed(monkeypatch):
    out = _summarize_with(monkeypatch, "记住：" + "；".join(f"第{i}件事" for i in range(9)))
    assert len(out["facts"]) <= 5, f"一次抽太多: {out['facts']}"


def test_no_want_facts_no_behaviour_change(monkeypatch):
    """没开这个开关的调用方 (正戏蒸馏) 逐字不变 —— 老路不许被动。"""
    out = _summarize_with(monkeypatch, "- 关系有进展。\n记住：不吃香菜", want_facts=False)
    assert "记住：不吃香菜" in out["memory"], "没开旗却把行吃掉了"
    assert out["facts"] == []
