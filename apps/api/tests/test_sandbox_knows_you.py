# -*- coding: utf-8 -*-
"""🪪 沙盒要吃玩家人设 (Yi:「根据用户角色的设定发展沙盒」)。

从前 seed_sandbox_cast 只喂世界观。于是你演一个刑警和演一个赌徒，开局撞见的是
同一批人——世界对你是谁毫无反应。而玩家那张卡本来就在调用处手上，只是没传下去。
"""
from app.engine import qwen, runtime as R


class _Spy:
    def __init__(self): self.seen = None
    def generate(self, p):
        if p.get("sandbox_cast"):
            self.seen = p
            return {"characters": [{"name": "阿甲", "persona_text": "x"}]}
        return {}


def _c():
    return {"story": {"id": "s", "sandbox": {"enabled": True},
                      "world_long": "一座下雨的港口城市。", "characters": [],
                      "acts": [{"index": 1, "title": "一"}], "locations": []}}


def test_the_opening_cast_is_told_who_you_are():
    llm = _Spy()
    R.seed_sandbox_cast(_c(), llm=llm, persona={"name": "蔡妍", "background": "重案组督察"})
    pl = (llm.seen or {}).get("player") or {}
    assert pl.get("name") == "蔡妍"
    assert "督察" in (pl.get("背景") or "")


def test_no_persona_still_works():
    """老调用方/没人设时照旧走得通 —— 别把它做成必填。"""
    llm = _Spy()
    R.seed_sandbox_cast(_c(), llm=llm)
    assert (llm.seen or {}).get("player") is None


def test_the_prompt_asks_for_people_who_relate_to_you():
    """传下去了但提示词不读＝没传。这条接缝今天栽过。"""
    sent = {}
    def _fake(url, key, body, **kw):
        sent["u"] = body["messages"][-1]["content"]
        class _R:
            @staticmethod
            def json(): return {"choices": [{"message": {"content": "{}"}}]}
        return _R()
    old = qwen._post_chat; qwen._post_chat = _fake
    try:
        llm = qwen.QwenLLM.__new__(qwen.QwenLLM)
        llm._url, llm._key, llm._model = "http://never", "k", "m"
        llm._sandbox_cast({"sandbox_cast": True, "worldview": "港口",
                           "player": {"name": "蔡妍", "背景": "重案组督察"}})
    finally:
        qwen._post_chat = old
    assert "蔡妍" in sent["u"] and "督察" in sent["u"]
    assert "有关系" in sent["u"], "没要求这批人跟玩家有瓜葛，那等于白传"
