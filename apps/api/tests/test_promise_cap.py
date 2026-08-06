# -*- coding: utf-8 -*-
"""🤝 约定不许无限立 (Yi 2026-08-06)。

Yi:「约定这部分要有一个计数，AI 角色不能无限和玩家有约定。比如之前线下有一个约定，
之后就不能在手机上还继续约玩家。」

查下来那条闸【已经存在】, 而且是单一入口: runtime.make_promise 同时守两道 ——
全局最多 MAX_OPEN_PROMISES 个 open, 每个角色同时只能有一个 open。三条产地
(正文 / 手机 / 活世界) 都走它。

真正的洞在另一头: _phone_exchange 给模型的载荷里【一条约定信息都没有】。模型不知道
已经约过了, 于是照样在短信正文里开口约; make_promise 拒收, 但那条短信已经发出去了。
玩家读到「明晚老地方见」, 账上却什么都没有 —— 本仓最忌的文与实分家。

生产实测 (178 局): 只有 3 局立过约定, 每局最多 1 个, 全是 open 从没兑现过 ——
所以这个漏点目前撞不上。修它是为了【主动引擎上线之后】: 角色一旦开始频繁提约会,
这条闸就要真扛事了。
"""
from app.engine import runtime


CONTENT = {"story": {
    "id": "s", "title": "t",
    "characters": [
        {"id": "a", "name": "阿彩", "is_lead": True, "persona_text": "洗头妹",
         "home_location_id": "hall"},
        {"id": "b", "name": "十二少", "persona_text": "四子之一", "home_location_id": "hall"},
    ],
    "acts": [{"index": 1, "title": "一"}],
    "locations": [{"id": "hall", "name": "祥记面档", "detail": "面档", "exits": []}],
    "phone": {"device": "手机"}}, "secrets": []}


def _st():
    st = runtime.default_state()
    st["location_id"] = "hall"
    st["contact_ids"] = ["a", "b"]
    # ⚠️ clock.slot 存的是【序号】不是名字 (0=晨 1=午 2=夜)。写成 "晨" 会让
    #    _time_index 的 int() 当场炸 —— 夹具坑, 记在这里省得下次再踩。
    st["clock"] = {"day": 1, "slot": 0, "turns_in_slot": 0}
    return st


def _mk(st, cid, what="巷口见", slot="夜", off=0):
    c = next(x for x in CONTENT["story"]["characters"] if x["id"] == cid)
    return runtime.make_promise(CONTENT, st, c,
                                {"what": what, "slot": slot, "day_offset": off},
                                runtime.tuning_for(CONTENT))


# ── 闸本身 (回归: 这是 Yi 要的那条, 别被谁顺手拆了) ────────────────────────────

def test_one_open_promise_per_character():
    """线下约过了, 同一个人就不能再约 —— 不管从哪条路来。"""
    st = _st()
    assert _mk(st, "a"), "第一个约定都立不上, 夹具坏了"
    assert _mk(st, "a", what="再约一次") is None, "同一个角色立了第二个约定"


def test_a_different_character_may_still_book():
    """闸是按人算的, 不是把整局锁死。"""
    st = _st()
    assert _mk(st, "a")
    assert _mk(st, "b"), "别人也被连坐了"


def test_the_global_cap_holds():
    assert runtime.MAX_OPEN_PROMISES >= 1
    st = _st()
    made = sum(1 for c in ("a", "b") if _mk(st, c))
    assert made <= runtime.MAX_OPEN_PROMISES


def test_a_closed_promise_frees_the_slot():
    """兑现或黄了之后才轮得到下一个 —— 否则一局只能约一次, 那是另一种坏。"""
    st = _st()
    assert _mk(st, "a")
    for p in st["promises"]:
        p["status"] = "done"
    assert _mk(st, "a", what="下次再约"), "约定结清了还占着坑"


# ── 洞: 模型不知道已经约过了 ──────────────────────────────────────────────────

def test_the_phone_prompt_is_told_about_open_promises():
    """不告诉它, 它就会在正文里接着约 —— 而账本悄悄拒收, 文与实分家。"""
    st = _st()
    _mk(st, "a", what="巷口见")
    got = runtime.open_promise_of(st, "a")
    assert got and "巷口见" in str(got), f"取不到这个角色手上的约定: {got}"


def test_no_promise_no_block():
    assert runtime.open_promise_of(_st(), "a") is None


def test_it_is_that_characters_own_promise_only():
    """认知边界: 十二少不该知道你跟阿彩约了什么。"""
    st = _st()
    _mk(st, "a", what="巷口见")
    assert runtime.open_promise_of(st, "b") is None


def test_a_closed_promise_is_not_reported_as_open():
    st = _st()
    _mk(st, "a")
    for p in st["promises"]:
        p["status"] = "done"
    assert runtime.open_promise_of(st, "a") is None


def test_it_reaches_the_phone_prompt_for_real():
    """进了 state 不算数, 要真进提示词, 而且要告诉模型拿它怎么办。"""
    from app.engine import qwen
    q = qwen.QwenLLM.__new__(qwen.QwenLLM)
    q._url = q._key = q._model = "x"
    box = {}

    def fake(url, key, body, **k):
        box["sys"] = body["messages"][0]["content"]
        box["user"] = "".join(str(m.get("content") or "") for m in body["messages"][1:])

        class R:
            def json(self):
                return {"choices": [{"message": {"content": '{"msgs":["嗯"]}'}}]}
        return R()

    old = qwen._post_chat
    qwen._post_chat = fake
    try:
        q._phone_reply({"phone_reply": True, "device": "手机", "shape": "normal",
                        "char": {"name": "阿彩", "persona_text": "洗头妹"},
                        "relation": "暧昧", "context": {},
                        "open_promise": {"what": "巷口见", "when": "今天夜里"},
                        "player_name": "蔡妍", "text": "在吗"})
    finally:
        qwen._post_chat = old
    t = box.get("sys", "") + box.get("user", "")
    assert "巷口见" in t, f"约定没进提示词:\n{t[:400]}"
    assert any(k in t for k in ("别再约", "不要再约", "已经约", "再定")), \
        "只贴了约定却没说要拿它怎么办"


def test_no_open_promise_no_block_in_the_prompt():
    """没约过就不该平白多一段提示词 (每条消息都在花 token)。"""
    from app.engine import qwen
    q = qwen.QwenLLM.__new__(qwen.QwenLLM)
    q._url = q._key = q._model = "x"
    box = {}

    def fake(url, key, body, **k):
        box["sys"] = body["messages"][0]["content"]

        class R:
            def json(self):
                return {"choices": [{"message": {"content": '{"msgs":["嗯"]}'}}]}
        return R()

    old = qwen._post_chat
    qwen._post_chat = fake
    try:
        q._phone_reply({"phone_reply": True, "device": "手机", "shape": "normal",
                        "char": {"name": "阿彩", "persona_text": "洗头妹"},
                        "relation": "暧昧", "context": {},
                        "player_name": "蔡妍", "text": "在吗"})
    finally:
        qwen._post_chat = old
    assert "别再约" not in box.get("sys", "")


# ── 拒收要留痕: 说了没记账, 得能被查出来 ──────────────────────────────────────

def test_a_refused_promise_leaves_an_audit_trail():
    """闸挡下的那一次正是「正文说了、账上没有」的现场 —— 不留痕就永远量不出来。"""
    st = _st()
    _mk(st, "a")
    n0 = len(st.get("last_audit") or [])
    _mk(st, "a", what="再约一次")
    au = [x for x in (st.get("last_audit") or []) if "promise" in str(x.get("e", ""))]
    assert len(st.get("last_audit") or []) > n0 and au, "拒收没留下任何痕迹"
