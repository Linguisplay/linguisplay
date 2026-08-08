# -*- coding: utf-8 -*-
"""🧾 P0 · 把「先判后写」验一次真伪 (整改方案 2026-08-08)。

双拍是两次独立的 HTTP 调用, 中间那道缝一直空着: 模型在 plan 拍申报了动作, 引擎却要
等到散文流完才结算。于是驳回永远来得太晚 —— 字已经在玩家眼前了。线上实弹:

    角色：要不要跟我去海边透透气
    玩家：跟她去海边
    旁白：海堤的风比商店街大得多⋯⋯     ← location_id 一动没动

这一刀只做一件事: 在两次调用之间插一次结算, 把【回执】写进渲染指令。
P0 只接 move_invite 一条路, 其余 44 个申报字段一个不碰。

验的是一个假设: 【模型拿到「驳回」, 能不能把戏圆得比我们禁止它更好。】
所以回执里的驳回必须带出路 (改约/指路/换个走得到的地方), 不能只有禁令 ——
只写禁令就退化成又一条「绝不许」, 那正是要拆掉的东西。
"""
import pytest

from app.engine import qwen, runtime


CONTENT = {"story": {
    "id": "s", "tuning": {"plan_render": 1},
    "characters": [{"id": "a", "name": "甲", "is_lead": True}],
    "acts": [{"index": 1, "title": "一"}],
    "locations": [{"id": "l1", "name": "旧巷", "detail": "x", "exits": ["老码头"]},
                  {"id": "dock", "name": "老码头", "detail": "x", "exits": ["旧巷"]},
                  {"id": "far", "name": "孤岛", "detail": "x", "exits": []}]}}


def _st():
    st = runtime.default_state()
    st["location_id"] = "l1"
    return st


# ── 回执本身 ──────────────────────────────────────────────────────────────────

def test_a_reachable_invite_gets_an_approval():
    r = runtime.plan_receipt(CONTENT, _st(), {"move_invite": "老码头"}, "我")
    assert "老码头" in r
    assert any(k in r for k in ("会问", "征求", "点头")), "没说清是玩家点头才走"
    assert "别替" in r or "不许替" in r, "没拦住模型替玩家答应"


def test_an_unreachable_invite_gets_a_refusal_with_a_way_out():
    """⚠️ 这一条是 P0 的命门。驳回只写禁令, 就退化成又一条「绝不许」——
    那正是整改要拆的东西。必须给模型可以演下去的选择。"""
    r = runtime.plan_receipt(CONTENT, _st(), {"move_invite": "孤岛"}, "我")
    assert "孤岛" in r
    assert any(k in r for k in ("去不了", "走不到", "到不了")), "没说清为什么不行"
    ways = sum(1 for k in ("改约", "下次", "指条路", "指路", "换", "别的地方") if k in r)
    assert ways >= 2, f"驳回没给出路, 只剩禁令: {r}"


def test_a_place_not_on_the_map_is_also_refused():
    r = runtime.plan_receipt(CONTENT, _st(), {"move_invite": "河堤"}, "我")
    assert r and ("去不了" in r or "不在册" in r or "还没有" in r)


def test_no_invite_no_receipt():
    """没申报就不许平白多一段 —— 每一拍都在花 token。"""
    assert runtime.plan_receipt(CONTENT, _st(), {}, "我") == ""
    assert runtime.plan_receipt(CONTENT, _st(), {"move_invite": ""}, "我") == ""


def test_the_receipt_never_calls_a_model():
    """🔒 P1 的头号风险先在这里钉死: 结算路径一旦混进模型调用, 它就顶在首字之前,
    TTFT 当场崩。这条断言是那份合同的界桩。"""
    def _boom(*a, **k):
        raise AssertionError("结算路径调用了模型")

    old_chat, old_stream = qwen._post_chat, qwen._post_chat_stream
    qwen._post_chat = qwen._post_chat_stream = _boom
    try:
        for where in ("老码头", "孤岛", "河堤"):
            runtime.plan_receipt(CONTENT, _st(), {"move_invite": where}, "我")
    finally:
        qwen._post_chat, qwen._post_chat_stream = old_chat, old_stream


def test_the_receipt_does_not_touch_state():
    """回执只是一句话。真正落账在结算级联里, 这里改了就是双重记账。"""
    st = _st()
    before = runtime.json.dumps(st, sort_keys=True) if hasattr(runtime, "json") else str(sorted(st.items(), key=str))
    runtime.plan_receipt(CONTENT, st, {"move_invite": "老码头"}, "我")
    after = runtime.json.dumps(st, sort_keys=True) if hasattr(runtime, "json") else str(sorted(st.items(), key=str))
    assert before == after, "回执把状态改了"


# ── 缝: 结算必须发生在渲染【之前】 ────────────────────────────────────────────

class _Resp:
    def __init__(self, args):
        self._args = args

    def json(self):
        return {"choices": [{"message": {"tool_calls": [
            {"function": {"name": "plan_turn", "arguments": self._args}}]}}]}


def _wire(monkeypatch, log, args='{"grounding":"x","outline":["甲开口"],"speech":"走吧。"}'):
    monkeypatch.setattr(qwen, "_post_chat",
                        lambda *a, **k: (log.append("plan"), _Resp(args))[1])

    def _stream(url, key, body, **kw):
        log.append("render")
        log.append(body["messages"][-1]["content"])
        yield "甲：「走吧。」"

    monkeypatch.setattr(qwen, "_post_chat_stream", _stream)


class _Probe(qwen.QwenLLM):
    def __init__(self):
        self._model = self._summary_model = self._aux_model = "m"
        self._url, self._key = "http://never", "k"


PROMPT = {"speaker_name": "甲", "speaker_persona": "x", "channel": "say",
          "persona": {"name": "我"}, "context": {}, "place": "旧巷", "cast": ["甲"]}


def test_settlement_runs_before_the_render_request(monkeypatch):
    """整条合同的命门。顺序错了, 这一刀就白做了。"""
    log = []
    _wire(monkeypatch, log)
    llm = _Probe()
    list(llm.plan_and_render(PROMPT, settle=lambda plan: (log.append("settle"), "")[1]))
    assert log[0] == "plan"
    assert log[1] == "settle", f"结算没排在渲染之前: {log[:3]}"
    assert log[2] == "render"


def test_the_receipt_reaches_the_render_directive(monkeypatch):
    log = []
    _wire(monkeypatch, log)
    llm = _Probe()
    list(llm.plan_and_render(PROMPT, settle=lambda plan: "【系统回执】那条路走不通。"))
    directive = log[2]
    assert "【系统回执】那条路走不通。" in directive


def test_the_settler_sees_what_the_model_declared(monkeypatch):
    """结算拿到的必须是这一拍模型【真的申报了什么】, 不是空壳。"""
    log, seen = [], {}
    _wire(monkeypatch, log,
          args='{"grounding":"x","outline":["甲相邀"],"speech":"走吧。","move_invite":"老码头"}')
    llm = _Probe()
    list(llm.plan_and_render(PROMPT, settle=lambda plan: (seen.update(plan), "")[1]))
    assert seen.get("move_invite") == "老码头"


def test_an_empty_receipt_adds_nothing(monkeypatch):
    log = []
    _wire(monkeypatch, log)
    llm = _Probe()
    list(llm.plan_and_render(PROMPT, settle=lambda plan: ""))
    assert "系统回执" not in log[2]


def test_a_broken_settler_never_breaks_the_turn(monkeypatch):
    """回执是加分项, 不是承重墙。它炸了这一拍照演。"""
    log = []
    _wire(monkeypatch, log)
    llm = _Probe()

    def _boom(plan):
        raise RuntimeError("结算炸了")

    out = list(llm.plan_and_render(PROMPT, settle=_boom))
    assert any(k == "token" for k, _ in out), "这一拍没演出来"
    assert any(k == "final" for k, _ in out)


# ── 老签名后端的兼容 (这一处我自己先写错过一版) ──────────────────────────────

class _OldBackend:
    """老签名的后端 (测试替身 / 第三方适配器): plan_and_render 不认识 settle。"""

    def __init__(self):
        self.runs = 0

    def generate(self, prompt):
        return {"beats": [], "affinity_delta": 0, "advance_act": False, "ending": None}

    def plan_and_render(self, prompt):
        self.runs += 1
        yield ("token", "x")
        yield ("final", {"beats": [], "affinity_delta": 0,
                         "advance_act": False, "ending": None})


class _BoomBackend:
    """新签名, 但生成器【体内】抛 TypeError —— 跟「签名不对」长得一模一样。"""

    def __init__(self):
        self.runs = 0

    def generate(self, prompt):
        return {}

    def plan_and_render(self, prompt, settle=None):
        self.runs += 1
        yield ("token", "x")
        raise TypeError("这是业务代码里的 bug，不是签名问题")


def test_an_old_signature_backend_still_runs():
    b = _OldBackend()
    out = list(runtime.plan_render_call(b, {"speaker_name": "甲"}, lambda p: "回执"))
    assert b.runs == 1
    assert any(k == "final" for k, _ in out)


def test_a_typeerror_from_inside_never_reruns_the_turn():
    """⚠️ 我第一版是 `try: fn(prompt, settle=…) except TypeError: fn(prompt)`。
    那样写, 生成器体内任何一个 TypeError 都会被当成「签名不对」而整拍重跑:
    两次计费、两份散文、两套裁决, 而且玩家会看到前半段演两遍。
    签名要在调用【之前】问清楚, 不能拿异常当判据。"""
    b = _BoomBackend()
    with pytest.raises(TypeError):
        list(runtime.plan_render_call(b, {"speaker_name": "甲"}, lambda p: ""))
    assert b.runs == 1, f"整拍被重跑了 {b.runs} 次"


def test_a_backend_without_the_method_falls_back_to_generate():
    class _Plain:
        def generate(self, prompt):
            return {"beats": [{"type": "dialogue", "speaker_name": "甲", "text": "嗯"}]}

    out = list(runtime.plan_render_call(_Plain(), {"speaker_name": "甲"}, lambda p: ""))
    assert out and out[0][0] == "final"


def test_no_settler_behaves_exactly_as_before(monkeypatch):
    """可逆: 不传 settle 时这条路跟从前一个字都不差。"""
    log = []
    _wire(monkeypatch, log)
    out = list(_Probe().plan_and_render(PROMPT))
    assert "系统回执" not in log[2]
    assert any(k == "final" for k, _ in out)
