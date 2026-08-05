# -*- coding: utf-8 -*-
"""📱 三刀之后的收尾 (Yi 2026-08-05「接着做吧」)。

评审合稿点名、上一轮没做的几处。每一条都是"平时看不见、出事时很难查"的那种:

  ① 上帝位是 pending 黑洞 —— 回合起点那句投递被 `mode != "god"` 挡着, 观剧局会
     无限攒待发, 谁也不投。
  ② 回溯 (rewind) 把整份 state 回卷, 但【已经落地的消息】和【还没到期的待发】会被
     一起卷走/卷回来 —— 玩家读过的消息凭空消失, 或者一条早该作废的话又活了。
  ③ metrics 的口径被我上一轮自己打断了: 报表读的是 `shape` 字段, 而延迟那条分支
     写的是 `asked` —— 一半的数据变成了「?」。这类"改了写侧忘了读侧"最难自己发现,
     所以钉一条源码守卫。
"""
import copy

import pytest

from app.engine import runtime

STORY = {"story": {"id": "s", "phone": {"enabled": True, "device": "手机"},
                   "tuning": {"turns_per_slot": 6},
                   "characters": [{"id": "a", "name": "甲", "is_lead": True},
                                  {"id": "b", "name": "乙"}],
                   "acts": [{"index": 1, "title": "一"}],
                   "locations": [{"id": "l1", "name": "旧巷", "detail": "x", "exits": []}]}}


def _st(**kw):
    st = runtime.default_state()
    st["location_id"] = "l1"
    st["met_ids"] = ["b"]
    st["contact_ids"] = ["b"]
    st["clock"] = {"day": 1, "slot": 1, "turns_in_slot": 0}
    st.update(kw)
    return st


def _park(st, n=2, due_offset=-1):
    th = runtime._thread(st, "b")
    th["pending"] = [{"text": f"第{i}句", "due_ts": runtime._wall_ts() + due_offset}
                     for i in range(n)]
    return th


# ── ① 上帝位不许是黑洞 ────────────────────────────────────────────────────
def test_god_mode_still_delivers_what_is_due():
    """观剧/上帝位不参与对话, 但【已经写好、时间也到了】的消息不该烂在信箱里。
    投递是纯搬运, 零 LLM —— 挡它没有任何理由, 只会让待发无限攒。"""
    c, st = copy.deepcopy(STORY), _st(mode="god")
    th = _park(st)
    assert runtime.deliver_due_phone(c, st) == 2, "上帝位把到期的消息扣下了"
    assert not th.get("pending")


def test_the_turn_start_delivery_is_not_gated_on_mode():
    """⚠️ 上一版这条测在【函数】上, 而闸其实在【调用点】—— 函数照跑, 观剧局照样黑洞,
    测试却是绿的。空转的守卫比没有守卫更坏。所以直接扫源码那一行。"""
    import pathlib
    import re
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "app" / "engine" / "runtime.py").read_text(encoding="utf-8")
    for m in re.finditer(r"deliver_due_phone\(content, state\)", src):
        head = src[max(0, m.start() - 220):m.start()]
        last_if = head.rfind("if ")
        near = head[last_if:] if last_if >= 0 else ""
        assert '!= "god"' not in near,             "回合起点的投递还被上帝位挡着 — 观剧局会无限攒待发"


def test_delivery_never_writes_new_words():
    """这条守着「无点击不推进」的边界: 投递只搬字, 一次 LLM 都不许打。
    (将来挂进世界心跳全靠这一点。)"""
    c, st = copy.deepcopy(STORY), _st()
    _park(st)

    class Boom:
        def generate(self, prompt):
            raise AssertionError("投递里打了 LLM 调用")

    import app.engine.llm as _llm
    old = _llm.get_llm
    _llm.get_llm = lambda *a, **k: Boom()
    try:
        assert runtime.deliver_due_phone(c, st) == 2
    finally:
        _llm.get_llm = old


# ── ② 回溯: 待发要跟着时间线一起被抹掉 ───────────────────────────────────
def test_rewind_drops_pending_written_after_the_rewind_point():
    """被抹掉的时间线要把它造的东西一起带走 —— 这是本仓回溯的既有法条
    (涌现的角色/地点就是这么处理的)。一条"还没送到"的消息更该如此:
    那句话是在一个已经不存在的回合里写的。"""
    st_before = _st()
    st_after = copy.deepcopy(st_before)
    _park(st_after, n=3, due_offset=9999)
    rolled = runtime.rewind_phone(st_after, st_before)
    assert not ((rolled.get("phone") or {}).get("threads") or {}).get("b", {}).get("pending"), \
        "回溯后那条时间线写的待发还在"


def test_rewind_keeps_messages_the_player_already_read():
    """反过来: 已经【送达并读过】的消息不许凭空消失。
    玩家读过的东西被抹掉, 比多留一条更伤 —— 那是"我明明看见过"的那种崩坏。"""
    st_before = _st()
    th0 = runtime._thread(st_before, "b")
    th0["msgs"] = [{"from": "them", "text": "早", "at": "第1天·晨"}]
    st_after = copy.deepcopy(st_before)
    th1 = runtime._thread(st_after, "b")
    th1["msgs"] = th1["msgs"] + [{"from": "me", "text": "在吗", "at": "第1天·午"}]
    _park(st_after, n=1, due_offset=9999)
    rolled = runtime.rewind_phone(st_after, st_before)
    texts = [m["text"] for m in (rolled["phone"]["threads"]["b"]["msgs"])]
    assert "早" in texts, "把回溯点之前就读过的消息也抹了"


def test_rewind_is_safe_when_there_was_no_phone_at_all():
    st_before = _st()
    st_after = copy.deepcopy(st_before)
    rolled = runtime.rewind_phone(st_after, st_before)
    assert rolled is st_before or isinstance(rolled, dict)


# ── ③ 写侧改了, 读侧必须跟上 ─────────────────────────────────────────────
def test_every_phone_shape_log_carries_the_fields_the_report_reads():
    """源码守卫: phone_shape 的写点与报表读的字段必须对得上。

    实弹 (我自己造的): 上一轮加延迟分支时写的是 asked=..., 而 metrics_report 读的是
    shape= —— 一半数据在报表里成了「?」, 而且没有任何测试会红。改了写侧忘了读侧,
    是这类观测代码最典型的烂法。"""
    import pathlib
    import re
    root = pathlib.Path(__file__).resolve().parents[1]
    src = (root / "app" / "engine" / "runtime.py").read_text(encoding="utf-8")
    rep = (root / "metrics_report.py").read_text(encoding="utf-8")

    writes = re.findall(r'log\(\s*"phone_shape"\s*,\s*([^)]*)\)', src)
    assert writes, "找不到 phone_shape 的写点"
    assert len(writes) >= 2, f"phone_shape 的写点只找到 {len(writes)} 个"
    read = set(re.findall(r'_pd\.get\("(\w+)"', rep))
    reported = read & {"asked", "got", "tier", "shape"}
    assert reported, "报表一个 phone_shape 字段都没读"
    # ⚠️ 必须【逐个写点】核对, 不能把所有写点的字段并起来看 —— 并起来的话, 只要有
    #    一个老写点还带着 shape=, 新加的那个漏了也照样绿, 而报表里那一半就是「?」。
    for w in writes:
        written = set(re.findall(r"(\w+)\s*=", w))
        missing = reported - written
        assert not missing, \
            f'这个写点缺 {missing}: log("phone_shape", {w.strip()[:70]}) — 报表里会是「?」'
