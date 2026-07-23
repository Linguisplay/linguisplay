"""到达建议 (Yi 2026-07-20 建议重做): /move 后的 chips 是确定性的两条 — 有人搭话+看看,
没人翻东西+看看 — 不花 LLM 调用; 下一回合导演随主拍的建议接手。"""

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


class NoCallLLM:
    """到达建议不许再打 LLM 调用 (重做前这里藏着一次独立小调用)。"""

    def generate(self, prompt):
        raise AssertionError(f"arrival_suggestions called the LLM: {list(prompt)}")


def test_arrival_chips_are_deterministic_two():
    st = runtime.default_state()
    st["location_id"] = "alley"
    got = runtime.arrival_suggestions(STORY, st, llm=NoCallLLM())
    assert got == ["跟乙搭句话", "先四下看看这地方"]


def test_arrival_empty_scene_and_god_mode():
    # 没人在场: 翻没搜过的东西 + 看看; 搜过了就只剩看看
    st = runtime.default_state()
    st["location_id"] = "alley"
    st["dead_character_ids"] = ["b"]
    assert runtime.arrival_suggestions(STORY, st, llm=NoCallLLM()) == \
        ["翻查生锈的铁柜", "先四下看看这地方"]
    st["searched_prop_ids"] = ["p1"]
    assert runtime.arrival_suggestions(STORY, st, llm=NoCallLLM()) == ["先四下看看这地方"]
    # god 模式无建议
    st3 = runtime.default_state()
    st3["mode"] = "god"
    assert runtime.arrival_suggestions(STORY, st3, llm=NoCallLLM()) == []
