# -*- coding: utf-8 -*-
"""📱 对抗验收抓出来的缺陷 (2026-08-05, 三路找茬 + 逐条证伪, 报 33 条成立 28 条)。

去重后是 9 个高危, 其中 5 个是手机三刀这两轮【亲手引入】的。每一条都在这里钉死。

  A. tier=="never" 根本没实现 —— _phone_due 只写了 soon/later/next_slot 三个分支,
     never 掉进注释写着 morning 的 else, 于是"这条不该有回音"变成"11 小时后送达"。
     配套坑: 投递侧那道"第二道闸"写的是 hp=="dead", 而 set_char_hp 全仓只写
     hurt/dying/None —— 那半句是死代码, dying 一个都拦不住。
  B. 延迟分支在 _apply_phone_judgments 之前 return —— 短信里 TA 答应的赴约/差事/
     约定全部丢账: 正文说了"我这就过来", 账上一笔没有。文与实分家。
  C. 互斥表只在 _phone_beat 内部成立 —— phone_send 事后按【模型输出】重新认形状
     (msgs[0].startswith("【已读") / len(msgs)>=4), 模型照样能自选 read/burst,
     绕开互斥表也绕开配额。判断权等于没收回来。
  D. char_sim[cid]["intent"] 全仓没有清除点 —— 说过一次"我去办件事"的角色, 此后
     每一条短信都判 later, 永远慢半拍。
  E. rewind_phone 无条件 pop("pending") —— 连【回溯点之前】就已经在路上的也一起
     作废, 玩家早先发的那条从此永远没有回音。
  F. 已读的短写法仍被解析器吞掉 (len(s)<=6 那条) —— 上一轮只修了 msgs[:3],
     没修这条。而现在引擎会【主动点名】read, 命中频率反而变高了。
  G. 观测里的 asked 是从模型输出反推的, 不是引擎点的名 —— "形状兑现率"在结构上
     永远 100%, 那个为了验收造的读口测不出任何不服从。
  H. _knows_key 把人称头整个抹掉 —— 「他妹妹在城南」和「你妹妹在城南」归一成同一条,
     后来的静默丢弃。合错比多存坏得多。
  I. 「记住：」正文无条件再劈一次半角冒号 —— 任何含 : 的事实 (时间/门牌/比例) 被
     截成尾巴, 存进账本的是一条【错的】事实。
"""
import copy

import pytest

from app.engine import runtime

STORY = {"story": {"id": "s", "phone": {"enabled": True, "device": "手机"},
                   "tuning": {"turns_per_slot": 6},
                   "characters": [{"id": "a", "name": "甲", "is_lead": True},
                                  {"id": "b", "name": "乙"}],
                   "acts": [{"index": 1, "title": "一"}],
                   "locations": [{"id": "l1", "name": "旧巷", "detail": "x", "exits": ["码头"]},
                                 {"id": "l2", "name": "码头", "detail": "x", "exits": ["旧巷"]}]}}


def _st(**kw):
    st = runtime.default_state()
    st["location_id"] = "l1"
    st["met_ids"] = ["b"]
    st["contact_ids"] = ["b"]
    st["clock"] = {"day": 1, "slot": 1, "turns_in_slot": 0}
    st.update(kw)
    return st


def _away(st):
    st["char_pins"] = {"b": "l2"}
    return st


class Reply:
    def __init__(self, msgs=None, **extra):
        self.msgs = msgs if msgs is not None else ["刚下工。"]
        self.extra = extra
        self.prompts = []

    def generate(self, p):
        self.prompts.append(p)
        if p.get("phone_reply"):
            return {"msgs": list(self.msgs), "closeness": 0, "romance": 0, **self.extra}
        if p.get("summarize"):
            return {"memory": "…", "facts": []}
        return {}


def _th(st):
    return ((st.get("phone") or {}).get("threads") or {}).get("b") or {}


# ══ A. never 必须是真的永不 ══════════════════════════════════════════════
def test_a_dying_character_gets_no_pending_at_all():
    """濒死的人判 never。never 不是"很久以后", 是【不会有回音】。
    实弹: 掉进 morning 分支后, 一个重伤濒死的人 11 小时后给你发了条短信。"""
    c, st = copy.deepcopy(STORY), _away(_st())
    runtime._sim(st, "b")["hp"] = "dying"
    view = runtime.phone_send(c, st, {"name": "我"}, "b", "你还撑得住吗", llm=Reply())
    assert not _th(st).get("pending"), f"判了 never 还排了待发: {_th(st).get('pending')}"
    assert view.get("replied") is False
    assert not view.get("pending"), "还跟客户端预告 TA 稍后会回"


def test_never_is_not_a_timestamp():
    c, st = copy.deepcopy(STORY), _st()
    due = runtime._phone_due(c, st, "never")
    assert due.get("due_ts") in (None, 0), f"never 被算成了一个到期戳: {due}"


def test_the_delivery_gate_uses_the_same_death_verdict_as_the_decision():
    """写侧判 never 认 (dead, dying), 读侧的闸却只认 hp=="dead" —— 而 set_char_hp
    全仓只写 hurt/dying/None, 那半句是【死代码】, dying 一个都拦不住。"""
    c, st = copy.deepcopy(STORY), _st()
    th = runtime._thread(st, "b")
    th["pending"] = [{"text": "等我", "due_ts": runtime._wall_ts() - 1}]
    runtime._sim(st, "b")["hp"] = "dying"
    assert runtime.deliver_due_phone(c, st) == 0, "濒死的人把消息发出去了"


# ══ B. 延迟里答应的事要落账 ═════════════════════════════════════════════
def test_a_promise_made_in_a_delayed_reply_is_still_booked():
    """短信正文说「我这就过来」, 账上必须有 —— 文与实不许分家。
    这条是我上一轮自己说"最不放心"的那处, 验收证实确实漏了。"""
    c, st = copy.deepcopy(STORY), _away(_st())
    runtime._sim(st, "b")["intent"] = "在码头卸货"
    runtime.phone_send(c, st, {"name": "我"}, "b", "你能过来一趟吗",
                       llm=Reply(["忙完就过去。"], coming=True))
    assert st.get("char_pins", {}).get("b") == st.get("location_id") \
        or (st.get("char_sim", {}).get("b") or {}).get("intent"), \
        "延迟回复里答应的赴约一笔没落账"


def test_a_task_taken_in_a_delayed_reply_is_still_booked():
    c, st = copy.deepcopy(STORY), _away(_st())
    runtime._sim(st, "b")["intent"] = "在码头卸货"
    runtime.phone_send(c, st, {"name": "我"}, "b", "帮我去问问老周",
                       llm=Reply(["回头我去问。"], task="去问老周"))
    got = (st.get("char_sim", {}).get("b") or {}).get("intent") or ""
    assert "老周" in got, f"延迟回复里应下的差事没落账: {got!r}"


# ══ C. 互斥表不许被事后重认绕开 ════════════════════════════════════════
def test_the_model_cannot_self_select_read_when_the_engine_said_otherwise():
    """引擎点了 normal, 模型自己写了「【已读：…】」—— 不许被认成 read。
    否则判断权等于没收回来, 而且绕过了每日配额。"""
    c, st = copy.deepcopy(STORY), _st()
    runtime.phone_send(c, st, {"name": "我"}, "b", "在吗",
                       llm=Reply(["【已读：懒得理你】", "稍后：算了没事"]))
    assert not _th(st).get("last_read"), "模型自选 read 被引擎认了"


def test_the_model_cannot_self_select_burst_either():
    c, st = copy.deepcopy(STORY), _st()
    st["clock"]["day"] = 1
    runtime.phone_send(c, st, {"name": "我"}, "b", "在吗",
                       llm=Reply(["a", "b", "c", "d", "e"]))
    book = (st.get("phone_shape_day") or {}).get("burst") or {}
    assert not book.get("b"), "模型自己刷屏, 却扣了 burst 的配额"


# ══ D. intent 要有清除点 ═══════════════════════════════════════════════
def test_an_intent_does_not_make_someone_slow_forever():
    """说过一次「我去办件事」的角色, 不能此后每一条短信都判 later。
    实弹: char_sim.intent 全仓没有任何清除点。"""
    c, st = copy.deepcopy(STORY), _away(_st())
    sim = runtime._sim(st, "b")
    sim["intent"] = "去码头取一件东西"
    sim["intent_at"] = runtime._time_index(st) - 9      # 九个时段以前的事了
    tier, _ = runtime._phone_beat(c, st, c["story"]["characters"][1], "在吗",
                                  False, runtime._thread(st, "b"))
    assert tier == "now", "陈年旧账还让 TA 一直慢半拍"


# ══ E. 回溯只作废【回溯点之后】排的待发 ═════════════════════════════════
def test_rewind_keeps_pending_that_predates_the_rewind_point():
    """玩家在回溯点【之前】发的那条, 回信还在路上 —— 回溯不该把它也弄没。
    不然玩家发过的消息永远等不到回音, 而且他根本不知道为什么。"""
    st_before = _st()
    th_b = runtime._thread(st_before, "b")
    th_b["pending"] = [{"text": "早先那条的回信", "due_ts": runtime._wall_ts() + 500}]
    st_after = copy.deepcopy(st_before)
    runtime._thread(st_after, "b")["pending"].append(
        {"text": "被抹掉那条时间线写的", "due_ts": runtime._wall_ts() + 900})
    rolled = runtime.rewind_phone(st_after, st_before)
    texts = [p["text"] for p in (rolled["phone"]["threads"]["b"].get("pending") or [])]
    assert "早先那条的回信" in texts, "把回溯点之前就在路上的也作废了"
    assert "被抹掉那条时间线写的" not in texts, "那条时间线写的话还活着"


# ══ F. 已读的短写法不许再被吞 ═══════════════════════════════════════════
def test_the_short_read_form_is_not_swallowed():
    """解析器那条 len(s)<=6 会把「【已读】」整条吞掉: msgs 清空、「稍后：」丢弃、
    last_read 不写。而现在引擎会主动点名 read, 命中频率反而变高。"""
    from app.engine import qwen

    class _R:
        def json(self):
            return {"choices": [{"message": {"content": "【已读】\n稍后：等我忙完"}}]}

    import types
    q = qwen.QwenLLM.__new__(qwen.QwenLLM)
    q._url = q._key = q._model = "x"
    q._post = None
    old = qwen._post_chat
    qwen._post_chat = lambda *a, **k: _R()
    try:
        out = q._phone_reply({"phone_reply": True, "char": {"name": "乙"},
                              "context": {}, "text": "在吗", "shape": "read"})
    finally:
        qwen._post_chat = old
    assert out.get("msgs"), "短写法被整条吞了 — 稍后那句也跟着没了"
    assert any("稍后" in m for m in out["msgs"]), f"补偿句丢了: {out['msgs']}"


# ══ G. 观测的 asked 必须是引擎点的名 ════════════════════════════════════
def test_the_metric_records_what_the_engine_ordered_not_what_came_back():
    """asked 若是从模型输出反推的, 兑现率在结构上永远 100% —— 那个为验收造的
    读口就测不出任何不服从, 等于白造。"""
    import pathlib
    import re
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "app" / "engine" / "runtime.py").read_text(encoding="utf-8")
    for m in re.finditer(r'log\(\s*"phone_shape"\s*,\s*([^)]*)\)', src):
        args = m.group(1)
        am = re.search(r"asked\s*=\s*(\w+)", args)
        assert am, f"写点没有 asked: {args[:60]}"
        assert am.group(1) != "_shape", \
            "asked 记的是【事后按模型输出反推】的 _shape — 兑现率恒 100%, 测不出不服从"


# ══ H. 事实去重不许把不同的人合成一条 ═══════════════════════════════════
def test_facts_about_different_people_do_not_merge():
    """「他妹妹在城南」和「你妹妹在城南」是两件事。归一时把人称头抹掉,
    第二条会被静默丢弃 —— 合错比多存坏得多。"""
    st = _st()
    runtime.knows_add(st, "b", ["他妹妹在城南读书"])
    runtime.knows_add(st, "b", ["你妹妹在城南读书"])
    assert len(runtime.knows_of(st, "b")) == 2, \
        f"不同人的同一件事被合成了一条: {runtime.knows_of(st, 'b')}"


# ══ I. 含冒号的事实不许被截断 ═══════════════════════════════════════════
def test_a_fact_containing_a_colon_survives_intact():
    """「记住：」的正文再劈一次半角冒号, 会把「约在 18:30」截成「30」——
    存进账本的是一条【错的】事实, 比没有更坏。"""
    from app.engine import qwen

    class _R:
        def json(self):
            return {"choices": [{"message": {"content": "- 聊了聊。\n记住：约在18:30见面；住在 3:2 号院"}}]}

    q = qwen.QwenLLM.__new__(qwen.QwenLLM)
    q._url = q._key = q._summary_model = "x"
    old = qwen._post_chat
    qwen._post_chat = lambda *a, **k: _R()
    try:
        out = q._summarize({"summarize": True, "prior_memory": "", "new_lines": [],
                            "want_facts": True})
    finally:
        qwen._post_chat = old
    assert any("18:30" in f for f in out["facts"]), \
        f"含冒号的事实被截断了: {out['facts']}"
