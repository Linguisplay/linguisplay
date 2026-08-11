# -*- coding: utf-8 -*-
"""📺 「上回」得知道上回发生了什么 (陌生玩家实弹 2026-08-10)。

除 Yi 和合伙人之外第一个真实用户，隔了 15 小时回来，读到的第一句是：

    〔上回〕栗山千夏把刚拿起的【章鱼烧】递向你这边⋯⋯含在那颗【没咬破的糖】里

而那一局里从头到尾没有章鱼烧、也没有糖。有的是豆大福、账本、烟。

根因跟今天别的问题同一个形状：让它总结，却不给它材料。build_parting_hook 的提示词里
只有地点/在场的人/待办话题标签/幕设定——没有一个字是【真的发生过的事】，模型只好照着
幕设定编一个像夏祭的小吃。

回归玩家读到的第一句话是编的，这比中间某一拍编得更贵。
"""
from app.engine import runtime as R


C = {"story": {"id": "s",
               "characters": [{"id": "a", "name": "千夏"}],
               "acts": [{"index": 1, "title": "一"}],
               "locations": [{"id": "l1", "name": "商店街", "detail": "x", "exits": []}]}}

LOG = [{"author": "engine", "type": "description", "speaker_name": None,
        "text": "她把皱巴巴的账本拍在柜台上。"},
       {"author": "engine", "type": "dialogue", "speaker_name": "千夏",
        "text": "一百八十万。……日元。"}]


class _Spy:
    def __init__(self): self.seen = None
    def generate(self, p):
        if p.get("parting"):
            self.seen = p
            return {"beats": [{"type": "description", "speaker_name": None, "text": "账本还摊着。"}]}
        return {}


def _st():
    st = R.default_state(); st["location_id"] = "l1"; st["act"] = 1
    return st


def test_the_recap_is_given_what_actually_happened():
    llm = _Spy()
    R.build_parting_hook(C, _st(), {"name": "我"}, llm, comeback=True, beat_log=LOG)
    rec = (llm.seen or {}).get("recent") or []
    assert rec, "「上回」还是不知道上回发生了什么"
    assert any("账本" in x for x in rec), f"喂进去的不是这一局: {rec}"


def test_it_is_framed_as_a_recap():
    llm = _Spy()
    out = R.build_parting_hook(C, _st(), {"name": "我"}, llm, comeback=True, beat_log=LOG)
    assert out and out[0]["text"].startswith("〔上回〕")


def test_no_log_still_produces_something():
    """拿不到历史时不许炸 —— 老调用方/空局照旧走得通。"""
    llm = _Spy()
    assert R.build_parting_hook(C, _st(), {"name": "我"}, llm, comeback=True)
