"""Scene changes refresh the next-step chips: /move regenerates suggestions grounded in
the place just entered and the people actually standing there — never the old scene."""

from app.engine import runtime

STORY = {
    "story": {"id": "s", "characters": [
        {"id": "a", "name": "甲", "is_lead": True, "home_location_id": "hall"},
        {"id": "b", "name": "乙", "home_location_id": "alley"},
    ], "acts": [{"index": 1, "title": "一"}],
       "locations": [
           {"id": "hall", "name": "门厅", "detail": "一盏吊灯", "exits": ["后巷"]},
           {"id": "alley", "name": "后巷", "detail": "潮湿", "exits": ["门厅"],
            "props": [{"id": "p1", "name": "生锈的铁柜", "detail": "锁着"}]},
       ]},
    "secrets": [],
}


class SuggLLM:
    """Returns scene-grounded chips and records what it was asked with."""

    def __init__(self, chips=None):
        self.chips = chips
        self.sugg_ctx = None

    def generate(self, prompt):
        if prompt.get("suggest"):
            self.sugg_ctx = prompt.get("sugg") or {}
            return {"suggestions": self.chips or []}
        return {"beats": [], "affinity_delta": 0, "advance_act": False, "ending": None}


def test_arrival_chips_ground_in_the_new_scene():
    llm = SuggLLM(chips=["乙哥，这柜子是谁的？", "让我翻翻这铁柜", "先看看四周"])
    st = runtime.default_state()
    st["location_id"] = "alley"
    got = runtime.arrival_suggestions(STORY, st, llm=llm)
    assert got == llm.chips
    # the model was anchored to THIS place and THIS cast — not the old scene's
    assert llm.sugg_ctx["place"] == "后巷"
    assert "刚走进" in llm.sugg_ctx["player_input"]
    assert llm.sugg_ctx["speaker"] == "乙" and llm.sugg_ctx["present"] == []


def test_arrival_falls_back_deterministically():
    st = runtime.default_state()
    st["location_id"] = "alley"
    got = runtime.arrival_suggestions(STORY, st, llm=SuggLLM(chips=[]))
    assert got == ["和乙搭话", "翻查生锈的铁柜", "看看四周"]
    # an empty scene still offers something to do; god mode gets nothing
    st2 = runtime.default_state()
    st2["location_id"] = "alley"
    st2["dead_character_ids"] = ["b"]
    assert "看看四周" in runtime.arrival_suggestions(STORY, st2, llm=SuggLLM(chips=[]))
    st3 = runtime.default_state()
    st3["mode"] = "god"
    assert runtime.arrival_suggestions(STORY, st3, llm=SuggLLM()) == []
