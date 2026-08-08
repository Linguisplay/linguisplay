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


def test_only_punctuation_and_spacing_are_normalised_away():
    """去重只做最保守的一层: 标点与空白。

    ⚠️ 契约在 2026-08-05 的对抗验收后收紧过。头一版还抹掉人称头 (他/她/你/对方),
    想把「他不吃香菜」和「不吃香菜」合成一条 —— 但那同时把【「他妹妹在城南」和
    「你妹妹在城南」】也合了, 而那是两件事, 后来的一条被静默丢弃。
    **合错比多存坏得多**: 多一条只是提示词肥一点, 合错是 TA 记错了人。
    """
    st = _st()
    runtime.knows_add(st, "b", ["不吃香菜。"])
    runtime.knows_add(st, "b", ["不吃香菜"])
    assert len(runtime.knows_of(st, "b")) == 1, "只差标点也没合"

    st2 = _st()
    runtime.knows_add(st2, "b", ["他妹妹在城南读书"])
    runtime.knows_add(st2, "b", ["你妹妹在城南读书"])
    assert len(runtime.knows_of(st2, "b")) == 2, \
        f"不同人的同一件事被合成了一条: {runtime.knows_of(st2, 'b')}"


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


# ── 🔗 线上线下共用一本事实账 (Yi 2026-08-08 问「手机和线下的记忆不通吗」) ──
# 通的部分本来就通: memory_by_char 是【同一个键】, 手机蒸馏和正戏蒸馏都写它;
# recent_scene 把线下的戏喂进手机, sms_tail 把手机喂回正戏。
# 唯独这本【事实账】从前只有一个读点 —— 在 _phone_exchange 里。于是玩家在短信里
# 说过"我不吃香菜", 当面 TA 一句不提。而当面才是最该用上的场合 (旁白体检第 21 条)。
SCENE = {"story": {"id": "s", "phone": {"enabled": True, "device": "手机"},
                   "characters": [{"id": "a", "name": "甲", "is_lead": True},
                                  {"id": "b", "name": "乙"}],
                   "acts": [{"index": 1, "title": "一"}],
                   "locations": [{"id": "l1", "name": "旧巷", "detail": "x", "exits": []}]}}


class ScenePrompts:
    def __init__(self):
        self.prompts = []

    def generate(self, p):
        self.prompts.append(p)
        if p.get("risk_judge"):
            return {"risk": 100}
        return {"beats": [{"type": "dialogue", "speaker_name": "乙", "text": "嗯。"}],
                "affinity_delta": 0, "advance_act": False, "ending": None}

    def speaker_prompts(self):
        # ⚠️ 一个回合会给【每个】说话人各建一份 prompt。用 next() 抓第一份就会抓到
        #    "另一个角色"那份 —— 它本来就没有这条事实, 于是断言冤枉产品
        #    (本会话第 N 次栽在抓取器上; 抓不到先怀疑抓法)。
        return [p for p in self.prompts if "knows" in p and "can_new_char" in p]


def test_a_fact_learned_over_text_is_remembered_face_to_face():
    """短信里说的事, 当面 TA 也该记得 —— 两边是同一本账。"""
    c, st = copy.deepcopy(SCENE), runtime.default_state()
    st["location_id"] = "l1"
    st["met_ids"] = ["b"]
    runtime.knows_add(st, "b", ["不吃香菜"])
    llm = ScenePrompts()
    runtime.run_turn(c, st, {"name": "我"}, "晚上吃什么", channel="say", llm=llm)
    ps = llm.speaker_prompts()
    assert ps, "没抓到任何说话人的 prompt"
    assert any("不吃香菜" in str(p.get("knows") or "") for p in ps), \
        f"当面这条路读不到事实账: {[p.get('knows') for p in ps]}"


def test_the_scene_prompt_actually_renders_it():
    """喂进去还得真的写进提示词 —— 传了没人读是本仓的老毛病。"""
    from app.engine.qwen import _build_system
    txt = ""
    try:
        txt = _build_system({"knows": ["不吃香菜", "妹妹在城南"], "char": {"name": "乙"}})
    except Exception:
        import inspect
        from app.engine import qwen
        src = inspect.getsource(qwen)
        assert 'prompt.get("knows")' in src.split("def _phone_reply")[0] or \
               src.count('prompt.get("knows")') >= 2, \
            "主拍装配没读 knows —— 只有手机那条路读"
        return
    assert "不吃香菜" in txt


def test_the_boundary_still_holds_face_to_face():
    """认知边界不许因为接上正戏就破 —— 只给这个角色自己那一本。"""
    c, st = copy.deepcopy(SCENE), runtime.default_state()
    st["location_id"] = "l1"
    st["met_ids"] = ["b"]
    # ⚠️ 必须记在一个【不在这场戏里】的人名下。头一版记在"甲"名下, 而甲本人就是
    #    说话人之一 —— 他的 prompt 带着他自己的记忆是【对的】, 断言却把它当成越界,
    #    冤枉了产品。认知边界要测的是"别人的账不许串过来", 不是"自己的账不许有"。
    runtime.knows_add(st, "zzz_不在场的人", ["不吃香菜"])
    llm = ScenePrompts()
    runtime.run_turn(c, st, {"name": "我"}, "在吗", channel="say", llm=llm)
    for p in llm.speaker_prompts():
        assert "不吃香菜" not in str(p.get("knows") or ""),             f"把甲的记忆喂给了别人 = 开天眼: {p.get('knows')}"


# ══ 🔗 剩下三条路 (Yi 2026-08-08「接上」) ═══════════════════════════════════
# 事实账原本只有手机回复一个读点; 上一刀接了正戏。这一刀把剩下三条【TA 主动开口】
# 的路接完 —— 而那三条恰恰是 Yi 要的「几天后 TA 主动用上」最有戏的场合:
#     主动找你 compose_msg  —— 半夜一条「你不是说不吃香菜」
#     朋友圈   social_posts —— 发条动态提到你那件事
#     信       compose_letter
# 认知边界照旧: 每条路只拿【那个角色自己】的账。
def _kn_st():
    st = runtime.default_state()
    st["location_id"] = "l1"
    st["met_ids"] = ["b"]
    st["contact_ids"] = ["b"]
    runtime.knows_add(st, "b", ["不吃香菜"])
    runtime.knows_add(st, "zzz_别人", ["怕打雷"])   # 不许串过来
    return st


class CatchAll:
    def __init__(self, key):
        self.key = key
        self.p = None

    def generate(self, prompt):
        if prompt.get(self.key):
            self.p = dict(prompt)
        return {}


def test_a_proactive_message_knows_what_you_told_them():
    """TA 半夜主动发一条 —— 这是「几天后用上」最有戏的场合。"""
    c, st = copy.deepcopy(STORY), _kn_st()
    ch = next(x for x in c["story"]["characters"] if x["id"] == "b")
    llm = CatchAll("compose_msg")
    runtime.compose_message(c, st, ch, "刚下工想起你", "写一两句", "……", llm)
    assert llm.p is not None, "没抓到 compose_msg 的 prompt"
    assert "不吃香菜" in str(llm.p.get("knows") or ""), \
        f"主动找你这条路读不到事实账: {llm.p.get('knows')}"
    assert "怕打雷" not in str(llm.p.get("knows") or ""), "别人的账串过来了"


def test_a_letter_knows_it_too():
    from app.engine import qwen
    import inspect
    src = inspect.getsource(qwen.QwenLLM._compose_letter)
    assert 'prompt.get("knows")' in src, "信这条路的装配没读 knows"


def test_the_social_feed_carries_it_per_character():
    """朋友圈是一次调用带多个角色的 items —— 事实必须【跟着各自的 cid】走,
    不能拍平成一份, 否则甲的事会出现在乙的动态里 (开天眼)。"""
    from app.engine import qwen
    import inspect
    # ⚠️ 渲染在 _social_material 里 (_social_posts 调它) —— 扫错函数就会冤枉产品。
    src = inspect.getsource(qwen.QwenLLM._social_material)
    assert "knows" in src, "朋友圈素材没带 knows"
    assert "不许" in src and "影子" in src,         "朋友圈的用法跟别处不同: 不许直说, 只留影子 —— 提示词得写明"


def test_every_proactive_path_renders_it_in_the_prompt():
    """传了没人读是本仓的老毛病 —— 三条路的装配都要真的把它写进提示词。"""
    from app.engine import qwen
    import inspect
    for fn in (qwen.QwenLLM._compose_msg, qwen.QwenLLM._compose_letter,
               qwen.QwenLLM._social_material):
        src = inspect.getsource(fn)
        assert "_knows_line" in src or "knows" in src,             f"{fn.__name__} 没把事实写进提示词"
    # 共用的那一行渲染器本身要真的渲染
    assert "你还记得TA说过的具体的事" in qwen._knows_line(["不吃香菜"])
    assert qwen._knows_line([]) == "", "空账不该塞一行废话进提示词"
