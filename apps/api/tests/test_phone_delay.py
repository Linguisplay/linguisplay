# -*- coding: utf-8 -*-
"""📱 延迟回复真的跑起来 (Yi 2026-08-05 三刀之 P0)。

生产实况: 延迟投递管线 (th["pending"] + deliver_due_phone) 建好了, **0 个线程用过**;
所有消息都在第 1 天、时间戳挤在同一分钟里 —— 整台手机没有时间维度。

查出来的根因是时间轴选错了: pending 的 deliver_at 走 _time_index, 粒度是【时段】,
而全舰默认 real_clock=1 让时段跟真实钟点走 (5-11/12-17/18-4) —— `now+1` 实际等待
1 分钟到 11 小时不等, 根本表达不了「隔一阵」; 而 turns_per_slot=0 的本 _time_index
恒定不动, pending 永不到期, 是个死信箱。

改法: 给 pending 加一条**墙钟轴** (UTC epoch 秒)。四个档位:
    soon      75~400 秒     刚下工/手上正忙
    later     20~60 分钟    在别处办事
    next_slot 下一个时段     作者班表说的这个钟点找不到人
    morning   下一个早上 6 点 深夜/被掳走

⚠️ 时长一律走 UTC (_wall_ts), 不许用 _now_for —— 那是【日历口径】(今天几号、
星期几), 换了时区会让到期时间跟着漂 (runtime.py 里已明文规定, living.due 同此)。
"""
import copy

import pytest

from app.engine import runtime

STORY = {"story": {"id": "s", "phone": {"enabled": True, "device": "手机"},
                   "tuning": {"turns_per_slot": 6},
                   "characters": [{"id": "a", "name": "甲", "is_lead": True},
                                  {"id": "b", "name": "乙"}],
                   "acts": [{"index": 1, "title": "一"}],
                   # ⚠️ 必须有第二个地点: 不然乙跟玩家同处 l1, phone_send 判 here=True,
                   #    当面聊天一律秒回 (那是对的) —— 延迟这条路根本走不到, 测试空转。
                   "locations": [{"id": "l1", "name": "旧巷", "detail": "x", "exits": ["码头"]},
                                 {"id": "l2", "name": "码头", "detail": "x", "exits": ["旧巷"]}]}}


class ReplyLLM:
    def __init__(self, msgs=None):
        self.msgs = msgs or ["刚下工。", "怎么了？"]
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        if prompt.get("phone_reply"):
            return {"msgs": list(self.msgs), "closeness": 1, "romance": 0}
        if prompt.get("summarize"):
            return {"memory": "…"}
        return {}

    def reply_prompt(self):
        return next((p for p in self.prompts if p.get("phone_reply")), None)


def _st(**kw):
    st = runtime.default_state()
    st["location_id"] = "l1"
    st["met_ids"] = ["b"]
    st["contact_ids"] = ["b"]
    st["clock"] = {"day": 1, "slot": 1, "turns_in_slot": 0}
    st.update(kw)
    return st


def _busy(st):
    """把乙支到别处 + 手上有活 → 判定必然走 later。
    钉在 l2 是为了让 phone_send 算出 here=False; intent 才是被测的那条判据。"""
    st["char_pins"] = {"b": "l2"}
    runtime._sim(st, "b")["intent"] = "去码头取一件东西"
    # ⏳ 应承有保质期 (INTENT_FRESH_SLOTS): 没盖时间戳的一律当过期 —— 老档里那些
    #    没人清除的陈年 intent 会让角色永远慢半拍, 所以默认从宽。这里盖上"刚应承"。
    runtime._sim(st, "b")["intent_at"] = runtime._time_index(st)
    return st


def _th(st):
    return ((st.get("phone") or {}).get("threads") or {}).get("b") or {}


# ── ⏱ 墙钟轴 ───────────────────────────────────────────────────────────────
def test_due_is_measured_on_a_wall_clock_not_the_slot_axis():
    c, st = copy.deepcopy(STORY), _st()
    due = runtime._phone_due(c, st, "soon")
    assert "due_ts" in due, f"没有墙钟到期戳: {due}"
    now = runtime._wall_ts()
    assert now < due["due_ts"] <= now + 900, f"soon 档到期时间离谱: {due['due_ts'] - now}s"


def test_the_four_tiers_are_ordered_in_time():
    c, st = copy.deepcopy(STORY), _st()
    now = runtime._wall_ts()
    gaps = {t: runtime._phone_due(c, st, t)["due_ts"] - now
            for t in ("soon", "later", "morning")}
    assert gaps["soon"] < gaps["later"], f"soon 该比 later 快: {gaps}"
    assert gaps["later"] < gaps["morning"] or gaps["morning"] > 3600, \
        f"morning 该是明早那么远: {gaps}"


def test_a_fictional_clock_story_gets_no_slot_gate():
    """时钟关掉的本 _time_index 冻住不动 —— 带时段门就是死信箱。"""
    c = copy.deepcopy(STORY)
    c["story"]["tuning"] = {"turns_per_slot": 0}
    due = runtime._phone_due(c, _st(), "next_slot")
    assert due.get("due_idx") is None, "时钟关掉的本还挂了时段门, pending 永不到期"
    assert due["due_ts"] > runtime._wall_ts(), "至少墙钟这条路要通"


# ── 📮 发出去之后: 不立刻回 ───────────────────────────────────────────────
def test_a_busy_character_does_not_answer_in_the_same_breath():
    c, st = copy.deepcopy(STORY), _busy(_st())
    llm = ReplyLLM()
    view = runtime.phone_send(c, st, {"name": "我"}, "b", "在吗", llm=llm)
    them = [m for m in _th(st).get("msgs") or [] if m.get("from") == "them"]
    assert not them, f"手上有活还秒回了: {them}"
    assert view.get("replied") is False


def test_the_words_are_written_now_and_parked_for_later():
    """模型这一刻就把词写好了 —— 延迟的是【送达】, 不是【生成】。
    (这样投递侧零 LLM, 世界心跳搬运也不违反「无点击不推进」。)"""
    c, st = copy.deepcopy(STORY), _busy(_st())
    runtime.phone_send(c, st, {"name": "我"}, "b", "在吗", llm=ReplyLLM(["刚下工。", "怎么了？"]))
    pend = _th(st).get("pending") or []
    assert len(pend) == 2, f"没把话存进待发: {pend}"
    assert [p["text"] for p in pend] == ["刚下工。", "怎么了？"]
    assert all(p.get("due_ts") for p in pend), "待发条目没有到期戳"


def test_the_player_is_told_something_is_coming_without_spoiling_it():
    c, st = copy.deepcopy(STORY), _busy(_st())
    view = runtime.phone_send(c, st, {"name": "我"}, "b", "在吗", llm=ReplyLLM())
    p = view.get("pending") or {}
    assert p.get("n") == 2, f"没告诉客户端有几条在路上: {view.get('pending')}"
    assert "text" not in str(p), "把待发的正文漏给客户端了 = 剧透"


def test_the_model_is_told_it_is_not_answering_now():
    c, st = copy.deepcopy(STORY), _busy(_st())
    llm = ReplyLLM()
    runtime.phone_send(c, st, {"name": "我"}, "b", "在吗", llm=llm)
    p = llm.reply_prompt()
    assert p, "没拿到 phone_reply 的 prompt"
    assert (p.get("reply_when") or {}).get("tier") == "later", \
        f"没把档位告诉模型: {p.get('reply_when')}"
    assert p.get("shape"), "没把形状告诉模型"


# ── 📬 到点才送到 ─────────────────────────────────────────────────────────
def test_nothing_arrives_before_its_time():
    c, st = copy.deepcopy(STORY), _busy(_st())
    runtime.phone_send(c, st, {"name": "我"}, "b", "在吗", llm=ReplyLLM())
    assert runtime.deliver_due_phone(c, st) == 0
    assert not [m for m in _th(st)["msgs"] if m.get("from") == "them"]


def test_it_arrives_once_the_clock_catches_up():
    c, st = copy.deepcopy(STORY), _busy(_st())
    runtime.phone_send(c, st, {"name": "我"}, "b", "在吗", llm=ReplyLLM())
    for p in _th(st)["pending"]:
        p["due_ts"] = runtime._wall_ts() - 1          # 时间到了
    assert runtime.deliver_due_phone(c, st) == 2
    them = [m["text"] for m in _th(st)["msgs"] if m.get("from") == "them"]
    assert them == ["刚下工。", "怎么了？"]
    assert not _th(st).get("pending"), "送完了还留着"
    assert int(_th(st).get("unread") or 0) >= 2, "没算未读"


# ── ⚰️ 判官点名的坑: 死人不许发消息 ───────────────────────────────────────
def test_the_dead_do_not_deliver():
    """玩家中午发消息判了延迟, 角色下午死了 —— 晚上不许弹出一条死人发来的消息。
    (本仓最忌的「文与实分家」; 三份设计稿都漏了这条。)"""
    c, st = copy.deepcopy(STORY), _busy(_st())
    runtime.phone_send(c, st, {"name": "我"}, "b", "在吗", llm=ReplyLLM())
    for p in _th(st)["pending"]:
        p["due_ts"] = runtime._wall_ts() - 1
    runtime._sim(st, "b")["hp"] = "dead"
    assert runtime.deliver_due_phone(c, st) == 0, "死人发出了消息"
    assert not _th(st).get("pending"), "死了还留着待发 = 复活时会集体喷发"


# ── 🚿 判官点名的坑: 攒一堆同时到期 = 意外刷屏 ───────────────────────────
def test_a_pile_of_due_messages_does_not_become_an_accidental_burst():
    c, st = copy.deepcopy(STORY), _busy(_st())
    th = runtime._thread(st, "b")
    th["pending"] = [{"text": f"第{i}句", "due_ts": runtime._wall_ts() - 1}
                     for i in range(8)]
    n = runtime.deliver_due_phone(c, st)
    assert n <= 3, f"一口气送了 {n} 条 — 引擎没点 burst, 玩家却吃到一屏"
    assert len(th.get("pending") or []) == 8 - n, "剩下的要顺延, 不是丢掉"


# ── 🧾 判官点名的坑: 待发不许无界增长 ─────────────────────────────────────
def test_pending_is_capped():
    c, st = copy.deepcopy(STORY), _busy(_st())
    th = runtime._thread(st, "b")
    th["pending"] = [{"text": f"x{i}", "due_ts": runtime._wall_ts() + 9999}
                     for i in range(40)]
    runtime.phone_send(c, st, {"name": "我"}, "b", "再问一次", llm=ReplyLLM())
    assert len(th.get("pending") or []) <= 12, \
        f"待发攒到 {len(th['pending'])} 条 — 会撑爆存档的 JSON 列"


# ── 🕰 老档兼容 ───────────────────────────────────────────────────────────
def test_old_pending_entries_written_on_the_slot_axis_still_deliver():
    """老档里是 {text, deliver_at}(时段轴)。虚构钟的本里那条轴冻住不动 = 死信箱,
    读侧一次性宽恕: 没有 due_ts 的老条目一律当已到期。"""
    c, st = copy.deepcopy(STORY), _st()
    th = runtime._thread(st, "b")
    th["pending"] = [{"text": "老消息", "deliver_at": 4}]
    assert runtime.deliver_due_phone(c, st) == 1, "老档的待发永远送不出去"
    assert [m["text"] for m in th["msgs"] if m.get("from") == "them"] == ["老消息"]
