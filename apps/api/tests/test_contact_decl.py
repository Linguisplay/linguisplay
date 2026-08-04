# -*- coding: utf-8 -*-
"""📇 联系方式申报口 (Yi 2026-07-28: 戏里号码给了, 通讯录却空着)。"""
from app.engine import qwen, runtime


def _story():
    # 这个文件测的是【申报→落账】那条合同 (文与实不许分家), 所以要把另外两条会
    # 独立给号的路关掉, 让申报路径单独受检:
    #   contact_on_meet=0 — 2026-08-04 上线的「照面即交换」
    #   contact_ask_t=99  — 「开口要就给」(同日从 10 降到 0; 本测试原本正是靠
    #                       交情 5 < 10 让这条路失败, 才验得出「没申报就不记账」)
    return {"story": {"id": "s", "characters": [{"id": "c1", "name": "蓝信一", "is_lead": True}],
                      "tuning": {"contact_on_meet": 0, "contact_ask_t": 99},
                      "acts": [{"index": 1, "title": "一"}],
                      "locations": [{"id": "l1", "name": "暗巷", "exits": []}]}, "secrets": []}


class _LLM:
    """主答者这一拍把号给了 (申报 contact_given)。"""
    def __init__(self, give=True):
        self.give = give
        self.prompts = []

    def generate(self, p):
        if p.get("summarize"):
            return {"memory": ""}
        if p.get("intro") or p.get("observe"):
            return {"beats": [{"type": "description", "speaker_name": None, "text": "x"}],
                    "affinity_delta": 0, "advance_act": False, "ending": None}
        self.prompts.append(p)
        out = {"beats": [{"type": "dialogue", "speaker_name": p.get("speaker_name"),
                          "text": "记我的号：9527。"}],
               "affinity_delta": 0, "advance_act": False, "ending": None}
        if self.give:
            out["contact_given"] = True
        return out


def test_schema_mounts_field_only_when_contact_missing():
    assert "contact_given" in str(qwen._render_tool({"can_give_contact": True, "place": "巷"},
                                                    "蓝信一", False, None, "say", "x"))
    assert "contact_given" not in str(qwen._render_tool({"can_give_contact": False, "place": "巷"},
                                                        "蓝信一", False, None, "say", "x"))


def test_parse_reads_the_declaration():
    import json
    d = qwen._parse_tool_args(json.dumps({"narration": "n", "speech": "s",
                                          "contact_given": True}), "蓝信一")
    assert d.get("contact_given") is True
    d2 = qwen._parse_tool_args(json.dumps({"narration": "n", "speech": "s"}), "蓝信一")
    assert not d2.get("contact_given")


def test_declared_contact_books_even_below_threshold():
    """交情不够也认: 戏里给了就真给 — 玩家死缠磨出来的号码也是靠剧情挣的。"""
    st = runtime.default_state()
    st["location_id"] = "l1"
    st["rel"] = {"c1": {"closeness": 5}}          # 远低于 CONTACT_ASK_T
    llm = _LLM(give=True)
    out = runtime.run_turn(_story(), st, {"name": "蔡妍"}, "把传呼机号报给他",
                           channel="say", llm=llm)
    assert runtime.has_contact(out["state"], "c1")
    assert any(a.get("e") == "contact.grant" for a in out["audit"])
    assert any(p.get("can_give_contact") for p in llm.prompts)   # 申报口确实挂载了


def test_no_declaration_no_booking():
    st = runtime.default_state()
    st["location_id"] = "l1"
    st["rel"] = {"c1": {"closeness": 5}}
    out = runtime.run_turn(_story(), st, {"name": "蔡妍"}, "把传呼机号报给他",
                           channel="say", llm=_LLM(give=False))
    assert not runtime.has_contact(out["state"], "c1")
