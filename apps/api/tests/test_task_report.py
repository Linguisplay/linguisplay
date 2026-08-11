# -*- coding: utf-8 -*-
"""📋 托事之后要有下文 (Yi 2026-08-11:「让 AI 角色去做一件事，合理就去做，然后汇报进度」)。

入口早就有：手机上说「帮我看看 X」，TA 答应了就写进 sim.intent，还留了痕 (phone.task)。
而那个字段写完就躺着——没有任何东西让 TA 去做、去回话。应承完了没有下文，比不能托事更伤。

「判断为合理」不新造判官：TA 当时是用自己的声音答应或推掉的，那就是判断，而且是最好的
那个——一个只看任务字符串的判官，判不出「这事该不该由我来办」。所以只补最后一环。
"""
from app.engine import runtime as R


C = {"story": {"id": "s", "phone": {"enabled": True},
               "characters": [{"id": "a", "name": "甲", "home_location_id": "l2"}],
               "acts": [{"index": 1, "title": "一"}],
               "locations": [{"id": "l1", "name": "旧巷", "detail": "x", "exits": ["码头"]},
                             {"id": "l2", "name": "码头", "detail": "x", "exits": ["旧巷"]}]}}


class _LLM:
    def __init__(self): self.reasons = []
    def generate(self, p):
        if p.get("compose_msg"):
            self.reasons.append(p.get("reason"))
            return {"msgs": ["查着呢。"]}
        return {}


def _st(intent="去码头问问四仔", ago=2, **kw):
    st = R.default_state()
    st["location_id"] = "l1"
    st["met_ids"] = ["a"]
    R.grant_contact_on_meet(C, st)
    sim = R._sim(st, "a")
    if intent:
        sim["intent"] = intent
        sim["intent_at"] = R._time_index(st) - ago
    st.update(kw)
    return st


def _run(st, llm):
    return R.phone_deliveries(C, st, here_ids=set(), llm=llm)


def test_a_taken_errand_comes_back_with_progress():
    llm = _LLM()
    out = _run(_st(), llm)
    assert "task_report" in llm.reasons, "应承完了没有下文"
    assert out, "汇报没发出来"


def test_nothing_taken_nothing_reported():
    llm = _LLM()
    _run(_st(intent=None), llm)
    assert "task_report" not in llm.reasons


def test_it_does_not_report_the_instant_it_is_taken():
    """刚领的事别转身就汇报 —— 那不像人。"""
    llm = _LLM()
    _run(_st(ago=0), llm)
    assert "task_report" not in llm.reasons


def test_it_reports_once_not_every_turn():
    """⚠️ 最容易做坏的一条: 每拍都回一次同一件事 = 刷屏。"""
    st, llm = _st(), _LLM()
    _run(st, llm); _run(st, llm); _run(st, llm)
    assert llm.reasons.count("task_report") == 1, f"复读了: {llm.reasons}"


def test_a_new_errand_gets_its_own_report():
    st, llm = _st(), _LLM()
    _run(st, llm)
    R._sim(st, "a")["intent"] = "改去问阿娣"
    R._sim(st, "a")["intent_at"] = R._time_index(st) - 2
    _run(st, llm)
    assert llm.reasons.count("task_report") == 2, "换了件事还不吭声"


def test_someone_standing_in_front_of_you_does_not_text():
    """人就在眼前, 当面说 —— 这条是 phone_deliveries 本来的家规, 别破。"""
    llm = _LLM()
    R.phone_deliveries(C, _st(), here_ids={"a"}, llm=llm)
    assert "task_report" not in llm.reasons
